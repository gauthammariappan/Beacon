"""Synthesize UPS alarm clips, detect beeps, and turn them into features.

Training audio is generated from patterns.json. The same detector and the
same feature function run on generated clips and on real recordings.
"""

from __future__ import annotations

import json
import wave
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import lfilter, resample_poly

ROOT = Path(__file__).resolve().parent
CATALOG_PATH = ROOT / "patterns.json"
SAMPLE_RATE = 16000

FEATURE_NAMES = [
    "duration_s",
    "n_pulses",
    "pulses_per_s",
    "median_width_ms",
    "min_period_ms",
    "max_period_ms",
    "duty_cycle",
    "longest_silence_ms",
    "longest_pulse_ms",
    "longest_silence_frac",
    "longest_pulse_frac",
]


def load_catalog(path: Path | None = None) -> dict:
    with open(path or CATALOG_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def _ms(spec: dict, key: str) -> tuple[float, float]:
    lo, hi = spec[key]
    return float(lo) / 1000.0, float(hi) / 1000.0


def _uniform(rng: np.random.Generator, bounds: tuple[float, float]) -> float:
    lo, hi = bounds
    if hi <= lo:
        return lo
    return float(rng.uniform(lo, hi))


def _tempo(rng: np.random.Generator) -> float:
    return float(rng.uniform(0.94, 1.06))


def colored_noise(rng: np.random.Generator, n: int, sigma: float, alpha: float) -> np.ndarray:
    white = rng.normal(0.0, 1.0, n).astype(np.float32)
    filtered = lfilter([alpha], [1.0, -(1.0 - alpha)], white).astype(np.float32)
    rms = float(np.sqrt(np.mean(filtered * filtered)) + 1e-8)
    return filtered * (sigma / rms)


def render(intervals: list[tuple[float, float]], duration: float, sr: int, rng: np.random.Generator, noise: tuple[float, float]) -> np.ndarray:
    n = max(1, int(round(duration * sr)))
    audio = np.zeros(n, dtype=np.float32)
    if intervals:
        freq = float(rng.uniform(1850.0, 3200.0))
        amp = float(rng.uniform(0.4, 0.95))
        harmonic = float(rng.uniform(0.25, 0.55))
        for start, end in intervals:
            i0 = max(0, int(start * sr))
            i1 = min(n, int(end * sr))
            if i1 - i0 < 8:
                continue
            times = np.arange(i0, i1, dtype=np.float32) / sr
            phase = float(rng.uniform(0.0, 2.0 * np.pi))
            omega = 2.0 * np.pi * freq
            segment = np.sin(omega * times + phase) + harmonic * np.sin(2.0 * omega * times + phase)
            segment /= 1.0 + harmonic
            attack = min(int(0.01 * sr), (i1 - i0) // 5)
            release = min(int(0.025 * sr), (i1 - i0) // 5)
            if attack > 1:
                segment[:attack] *= np.linspace(0.0, 1.0, attack, dtype=np.float32)
            if release > 1:
                segment[-release:] *= np.linspace(1.0, 0.0, release, dtype=np.float32)
            audio[i0:i1] += segment * amp * float(rng.uniform(0.85, 1.0))
    sigma = float(rng.uniform(*noise))
    alpha = float(rng.uniform(0.03, 0.15))
    audio += colored_noise(rng, n, sigma, alpha)
    return np.clip(audio, -1.0, 1.0)


def _clip_intervals(intervals: list[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    kept = []
    for start, end in intervals:
        start = max(0.0, start)
        end = min(duration, end)
        if end - start >= 0.04:
            kept.append((start, end))
    return kept


def _crop(audio: np.ndarray, intervals: list[tuple[float, float]], sr: int, t0: float, t1: float) -> tuple[np.ndarray, list[tuple[float, float]]]:
    i0 = max(0, int(round(t0 * sr)))
    i1 = min(len(audio), int(round(t1 * sr)))
    i1 = max(i1, min(len(audio), i0 + int(0.25 * sr)))
    duration = (i1 - i0) / sr
    shifted = []
    for start, end in intervals:
        start = max(0.0, start - t0)
        end = min(duration, end - t0)
        if end - start >= 0.04:
            shifted.append((float(start), float(end)))
    return audio[i0:i1].copy(), shifted


def _place_burst(spec: dict, rng: np.random.Generator, duration: float) -> list[tuple[float, float]]:
    tempo = _tempo(rng)
    beep = _uniform(rng, _ms(spec, "beep_ms")) * tempo
    gap = _uniform(rng, _ms(spec, "intra_gap_ms")) * tempo
    cycle = _uniform(rng, _ms(spec, "cycle_ms")) * tempo
    count = int(spec["beeps_per_burst"])
    step = beep + gap
    start = -float(rng.uniform(0.0, cycle))
    intervals = []
    while start < duration:
        for index in range(count):
            if rng.random() < 0.04:
                continue
            onset = start + index * step
            intervals.append((onset, onset + beep))
        start += cycle * float(rng.uniform(0.98, 1.02))
    return _clip_intervals(intervals, duration)


def _burst_snip(audio, intervals, sr, rng):
    if not intervals:
        return audio, intervals
    groups = [[intervals[0]]]
    for interval in intervals[1:]:
        if interval[0] - groups[-1][-1][1] < 0.55:
            groups[-1].append(interval)
        else:
            groups.append([interval])
    group = groups[int(rng.integers(0, len(groups)))]
    t0 = group[0][0] - float(rng.uniform(0.12, 0.55))
    t1 = group[-1][1] + float(rng.uniform(0.15, 0.75))
    return _crop(audio, intervals, sr, t0, t1)


def _synth_burst(spec, rng, sr, window_s):
    intervals = _place_burst(spec, rng, window_s)
    audio = render(intervals, window_s, sr, rng, (0.004, 0.025))
    if rng.random() < 0.5:
        audio, intervals = _burst_snip(audio, intervals, sr, rng)
    return audio, intervals


def _sample_pair(spec, rng) -> tuple[float, float, float]:
    beep_bounds = _ms(spec, "beep_ms")
    gap_bounds = _ms(spec, "intra_gap_ms")
    period_bounds = _ms(spec, "pair_period_ms")
    min_inter = float(spec["min_inter_silence_ms"]) / 1000.0
    tempo = _tempo(rng)
    for _ in range(30):
        beep = _uniform(rng, beep_bounds) * tempo
        intra = _uniform(rng, gap_bounds) * tempo
        period = _uniform(rng, period_bounds) * tempo
        if period - (2.0 * beep + intra) >= min_inter:
            return beep, intra, period
    return 0.12 * tempo, 0.08 * tempo, 0.75 * tempo


def _synth_paired(spec, rng, sr, window_s):
    roll = float(rng.random())
    if roll < 0.25:
        beep, intra, _period = _sample_pair(spec, rng)
        pad_l = float(rng.uniform(0.12, 0.45))
        pad_r = float(rng.uniform(0.12, 0.55))
        duration = pad_l + beep + intra + beep + pad_r
        intervals = [(pad_l, pad_l + beep), (pad_l + beep + intra, pad_l + beep + intra + beep)]
        if rng.random() < 0.04:
            intervals = intervals[:1]
        audio = render(intervals, duration, sr, rng, (0.004, 0.02))
        return audio, intervals

    duration = window_s if roll < 0.65 else float(rng.uniform(3.0, 6.0))
    beep, intra, period = _sample_pair(spec, rng)
    start = -float(rng.uniform(0.0, period))
    intervals = []
    while start < duration:
        if rng.random() >= 0.04:
            intervals.append((start, start + beep))
        second = start + beep + intra
        if rng.random() >= 0.04:
            intervals.append((second, second + beep))
        start += period * float(rng.uniform(0.98, 1.02))
    intervals = _clip_intervals(intervals, duration)
    audio = render(intervals, duration, sr, rng, (0.004, 0.02))
    return audio, intervals


def _synth_pulse(spec, rng, sr, window_s):
    tempo = _tempo(rng)
    beep = _uniform(rng, _ms(spec, "beep_ms")) * tempo
    cycle = _uniform(rng, _ms(spec, "cycle_ms")) * tempo
    fast = cycle < 1.5
    if fast and rng.random() < 0.4:
        duration = float(rng.uniform(2.5, 6.0))
    else:
        duration = window_s
    start = -float(rng.uniform(0.0, cycle))
    intervals = []
    while start < duration:
        if rng.random() >= 0.04:
            intervals.append((start, start + beep))
        start += cycle * float(rng.uniform(0.98, 1.02))
    intervals = _clip_intervals(intervals, duration)
    audio = render(intervals, duration, sr, rng, (0.004, 0.025))
    return audio, intervals


def _synth_single(spec, rng, sr, window_s):
    beep = _uniform(rng, _ms(spec, "beep_ms")) * _tempo(rng)
    if rng.random() < 0.6:
        pad_l = float(rng.uniform(0.4, 1.2))
        pad_r = float(rng.uniform(0.4, 1.2))
        duration = pad_l + beep + pad_r
        intervals = [(pad_l, pad_l + beep)]
    else:
        duration = window_s
        onset = float(rng.uniform(0.4, max(0.5, duration - beep - 0.4)))
        intervals = [(onset, onset + beep)]
    audio = render(intervals, duration, sr, rng, (0.003, 0.018))
    return audio, intervals


def _synth_tone(spec, rng, sr, window_s):
    del spec
    duration = float(rng.uniform(2.0, window_s))
    # A few milliseconds of fade keeps the speaker from clicking. The tone
    # still occupies the whole clip, which is what "solid tone" means.
    fade = 0.015
    intervals = [(0.0, duration)]
    audio = render(intervals, duration, sr, rng, (0.002, 0.012))
    # Soften the exact sample at the edges after render's own attack.
    edge = max(1, int(fade * sr))
    if len(audio) > 2 * edge:
        audio[:edge] *= np.linspace(0.0, 1.0, edge, dtype=np.float32)
        audio[-edge:] *= np.linspace(1.0, 0.0, edge, dtype=np.float32)
    return audio, [(0.0, duration)]


def _synth_repeating_long(spec, rng, sr, window_s):
    del window_s
    beep_bounds = _ms(spec, "beep_ms")
    cycle_bounds = _ms(spec, "cycle_ms")
    min_gap = float(spec["min_gap_ms"]) / 1000.0
    beep, cycle = beep_bounds[0], cycle_bounds[0]
    for _ in range(40):
        tempo = _tempo(rng)
        beep = _uniform(rng, beep_bounds) * tempo
        cycle = _uniform(rng, cycle_bounds) * tempo
        if cycle - beep >= min_gap:
            break
    repeats = 2 if rng.random() < 0.75 else 3
    pad_l = float(rng.uniform(0.2, 1.2))
    pad_r = float(rng.uniform(0.2, 1.5))
    duration = pad_l + (repeats - 1) * cycle + beep + pad_r
    intervals = []
    for index in range(repeats):
        onset = pad_l + index * cycle
        intervals.append((onset, onset + beep))
    audio = render(intervals, duration, sr, rng, (0.002, 0.015))
    return audio, intervals


def _synth_negative(spec, rng, sr, window_s):
    del spec
    kind = int(rng.integers(0, 4))
    if kind == 0:
        duration = float(rng.uniform(1.0, window_s))
        audio = colored_noise(rng, int(duration * sr), float(rng.uniform(0.001, 0.01)), 0.2)
        return np.clip(audio, -1, 1), []
    if kind == 1:
        duration = float(rng.uniform(1.0, window_s))
        audio = colored_noise(rng, int(duration * sr), float(rng.uniform(0.01, 0.06)), float(rng.uniform(0.01, 0.08)))
        return np.clip(audio, -1, 1), []
    if kind == 2:
        duration = float(rng.choice([window_s, float(rng.uniform(1.0, 8.0))]))
        beep = float(rng.uniform(0.06, 0.28))
        onset = float(rng.uniform(0.1, max(0.15, duration - beep - 0.1)))
        intervals = [(onset, onset + beep)]
        audio = render(intervals, duration, sr, rng, (0.004, 0.03))
        return audio, intervals

    duration = float(rng.choice([window_s, float(rng.uniform(3.0, 12.0))]))
    intervals = []
    for _attempt in range(25):
        count = int(rng.integers(2, 7))
        gaps = [float(rng.uniform(0.55, 8.0)) for _ in range(count - 1)]
        if max(gaps) / min(gaps) < 1.8:
            continue
        cursor = float(rng.uniform(0.1, 1.0))
        draft = []
        beep = float(rng.uniform(0.06, 0.22))
        for gap in [0.0, *gaps]:
            cursor += gap
            if cursor + beep >= duration - 0.05:
                break
            draft.append((cursor, cursor + beep))
            cursor += beep
        if len(draft) >= 2:
            intervals = draft
            break
    audio = render(intervals, duration, sr, rng, (0.004, 0.03))
    return audio, intervals


def synthesize(spec: dict, rng: np.random.Generator, sr: int = SAMPLE_RATE, window_s: float = 32.0):
    kind = spec["kind"]
    if kind == "burst":
        return _synth_burst(spec, rng, sr, window_s)
    if kind == "paired":
        return _synth_paired(spec, rng, sr, window_s)
    if kind == "pulse":
        return _synth_pulse(spec, rng, sr, window_s)
    if kind == "single":
        return _synth_single(spec, rng, sr, window_s)
    if kind == "tone":
        return _synth_tone(spec, rng, sr, window_s)
    if kind == "repeating_long":
        return _synth_repeating_long(spec, rng, sr, window_s)
    if kind == "negative":
        return _synth_negative(spec, rng, sr, window_s)
    raise ValueError(f"unknown pattern kind {kind}")


def _is_tonal(audio: np.ndarray, sr: int) -> bool:
    """True when the slice has a narrow peak between 1.4 and 4.5 kHz.

    Autocorrelation is a poor test here: smooth fan noise is also correlated
    at the short lags of a 2 kHz tone. A sine stands out as a narrow spectral
    peak instead.
    """
    segment = np.asarray(audio, dtype=np.float64)
    if segment.size < int(0.03 * sr):
        return False
    segment = segment - float(segment.mean())
    if float(np.dot(segment, segment)) < 1e-10:
        return False
    window = np.hanning(segment.size)
    spectrum = np.abs(np.fft.rfft(segment * window))
    freqs = np.fft.rfftfreq(segment.size, 1.0 / sr)
    band_index = np.flatnonzero((freqs >= 1400.0) & (freqs <= 4500.0))
    if band_index.size < 8:
        return False
    band = spectrum[band_index]
    peak_at = int(np.argmax(band))
    peak = float(band[peak_at])
    lo = max(0, peak_at - 3)
    hi = min(band.size, peak_at + 4)
    side = np.concatenate([band[:lo], band[hi:]])
    if side.size < 5:
        return False
    floor = float(np.median(side) + 1e-12)
    return peak / floor >= 12.0


def _merge(pulses: list[tuple[float, float]], max_gap: float) -> list[tuple[float, float]]:
    if not pulses:
        return []
    merged = [[pulses[0][0], pulses[0][1]]]
    for start, end in pulses[1:]:
        if start - merged[-1][1] <= max_gap:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def detect_pulses(audio: np.ndarray, sr: int) -> list[tuple[float, float]]:
    """Return beep intervals in seconds.

    A beep is a stretch of pitched energy. Fan noise and thumps are dropped
    because they are not tonal in the piezo band. The peak is the maximum of
    the smoothed envelope, not a high percentile: a beep every 10 seconds is
    less than one percent of the clip, so a 95th percentile never sees it.
    """
    samples = np.asarray(audio, dtype=np.float32)
    if samples.size < int(0.05 * sr):
        return []
    samples = samples - float(samples.mean())
    window = max(1, int(0.012 * sr))
    kernel = np.ones(window, dtype=np.float32) / window
    envelope = np.convolve(np.abs(samples), kernel, mode="same")
    # A low percentile, not the median. A long beep can be most of a short
    # clip, so the median is the beep and only the quiet tail shows the floor.
    floor = float(np.percentile(envelope, 5))
    peak = float(np.max(envelope))
    if peak < 1e-4:
        return []
    duration = samples.size / sr
    quiet_frac = float(np.mean(envelope < 0.35 * peak))
    if quiet_frac < 0.025 and _is_tonal(samples, sr):
        return [(0.0, float(duration))]
    if peak < floor * 2.2:
        return []
    threshold = floor + 0.40 * (peak - floor)
    active = envelope > threshold
    edges = np.diff(active.astype(np.int8), prepend=np.int8(0))
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1)
    if active[-1]:
        ends = np.append(ends, samples.size)
    count = min(len(starts), len(ends))
    pulses = []
    for start, end in zip(starts[:count], ends[:count]):
        if end - start >= int(0.03 * sr):
            pulses.append((start / sr, end / sr))
    pulses = _merge(pulses, 0.03)
    tonal = []
    for start, end in pulses:
        i0 = max(0, int(start * sr))
        i1 = min(samples.size, int(end * sr))
        if _is_tonal(samples[i0:i1], sr):
            tonal.append((float(start), float(end)))
    return tonal


def extract_features(pulses: list[tuple[float, float]], duration_s: float) -> np.ndarray:
    duration_s = max(float(duration_s), 1e-3)
    cleaned = []
    for start, end in pulses:
        start = min(duration_s, max(0.0, float(start)))
        end = min(duration_s, max(0.0, float(end)))
        if end - start >= 0.02:
            cleaned.append((start, end))
    cleaned.sort()

    widths = [(end - start) for start, end in cleaned]
    onsets = [start for start, _end in cleaned]
    periods = np.diff(onsets) if len(onsets) >= 2 else np.array([])
    silence_gaps = []
    cursor = 0.0
    for start, end in cleaned:
        silence_gaps.append(start - cursor)
        cursor = end
    silence_gaps.append(duration_s - cursor)
    longest_silence = max(silence_gaps) if silence_gaps else duration_s
    longest_pulse = max(widths) if widths else 0.0
    duty = float(sum(widths) / duration_s) if widths else 0.0

    values = [
        duration_s,
        float(len(cleaned)),
        float(len(cleaned) / duration_s),
        float(np.median(widths) * 1000.0) if widths else 0.0,
        float(periods.min() * 1000.0) if len(periods) else 0.0,
        float(periods.max() * 1000.0) if len(periods) else 0.0,
        duty,
        float(longest_silence * 1000.0),
        float(longest_pulse * 1000.0),
        float(longest_silence / duration_s),
        float(longest_pulse / duration_s),
    ]
    return np.asarray(values, dtype=np.float64)


def detection_precision(true_intervals: list[tuple[float, float]], detected: list[tuple[float, float]]) -> float:
    """How much of each detection actually overlaps a real beep.

    Recall alone stays high if one huge detection swallows every beep.
    """
    if not detected:
        return 1.0 if not true_intervals else 0.0
    scores = []
    for det_start, det_end in detected:
        overlap = 0.0
        for start, end in true_intervals:
            overlap += max(0.0, min(end, det_end) - max(start, det_start))
        scores.append(overlap / max(det_end - det_start, 1e-6))
    return float(np.mean(scores))


def detection_recall(true_intervals: list[tuple[float, float]], detected: list[tuple[float, float]]) -> float:
    if not true_intervals:
        return 1.0 if not detected else 0.0
    hits = 0
    for start, end in true_intervals:
        length = end - start
        for det_start, det_end in detected:
            overlap = max(0.0, min(end, det_end) - max(start, det_start))
            if length > 0 and overlap >= 0.5 * length:
                hits += 1
                break
    return hits / len(true_intervals)


def load_audio(path: str | Path, target_sr: int = SAMPLE_RATE) -> tuple[np.ndarray, int]:
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", wavfile.WavFileWarning)
        source_sr, data = wavfile.read(path)
    data = np.asarray(data)
    if np.issubdtype(data.dtype, np.integer):
        audio = data.astype(np.float32) / np.iinfo(data.dtype).max
    else:
        audio = data.astype(np.float32)
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    audio = np.nan_to_num(audio)
    audio = audio - float(audio.mean())
    if int(source_sr) != target_sr:
        factor = np.gcd(int(source_sr), target_sr)
        audio = resample_poly(audio, target_sr // factor, int(source_sr) // factor).astype(np.float32)
    return audio, target_sr


def write_wav(path: str | Path, audio: np.ndarray, sr: int = SAMPLE_RATE) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.clip(audio, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sr)
        handle.writeframes(pcm.tobytes())
