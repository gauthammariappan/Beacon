"""Generate 2500 Hz test alarm WAVs and synthetic data center noise for phone playback.

Patterns generated into beeps/ directory:
1. P1_on_battery.wav: 4 short beeps + 4s pause (APC UPS On Battery)
2. P2_low_battery.wav: Rapid recurring beeps (< 1s gap)
3. P3_overload.wav: Continuous 2500 Hz steady tone (> 600 ms)
4. datacenter_fan_noise.wav: 75 dB ambient background fan and air turbulence
"""

from __future__ import annotations

import math
from pathlib import Path
import struct
import wave
import numpy as np


SAMPLE_RATE = 16000
BEEP_FREQ = 2500.0  # Hz


def apply_envelope(samples: np.ndarray, fade_ms: float = 5.0, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Apply linear fade-in and fade-out to prevent speaker pop/clicks."""
    fade_len = int(sr * (fade_ms / 1000.0))
    if fade_len > len(samples) // 2:
        fade_len = len(samples) // 2
    if fade_len <= 0:
        return samples

    ramp_in = np.linspace(0.0, 1.0, fade_len)
    ramp_out = np.linspace(1.0, 0.0, fade_len)
    samples[:fade_len] *= ramp_in
    samples[-fade_len:] *= ramp_out
    return samples


def generate_tone(duration_s: float, freq: float = BEEP_FREQ, amplitude: float = 0.8) -> np.ndarray:
    """Generate a pure sine tone with anti-click envelopes."""
    t = np.linspace(0.0, duration_s, int(SAMPLE_RATE * duration_s), endpoint=False)
    tone = amplitude * np.sin(2.0 * np.pi * freq * t)
    return apply_envelope(tone, fade_ms=4.0)


def generate_silence(duration_s: float) -> np.ndarray:
    """Generate silence buffer."""
    return np.zeros(int(SAMPLE_RATE * duration_s), dtype=np.float32)


def save_wav(filename: Path | str, audio: np.ndarray, sr: int = SAMPLE_RATE) -> None:
    """Save 16-bit mono PCM WAV file."""
    filepath = Path(filename)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    # Clip and convert float [-1.0, 1.0] to int16
    audio_clipped = np.clip(audio, -1.0, 1.0)
    audio_int16 = (audio_clipped * 32767.0).astype(np.int16)

    with wave.open(str(filepath), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(audio_int16.tobytes())

    print(f"[WAV] Saved {filepath} ({len(audio) / sr:.1f}s, {sr} Hz)")


def generate_p1_on_battery(repeats: int = 3) -> np.ndarray:
    """Pattern P1: 4 short beeps (150 ms each, 150 ms gap), followed by a 4 s pause."""
    beep = generate_tone(0.15, BEEP_FREQ)
    intra_gap = generate_silence(0.15)
    pause = generate_silence(4.0)

    # 4 beeps burst
    one_cycle = np.concatenate([
        beep, intra_gap,
        beep, intra_gap,
        beep, intra_gap,
        beep, pause,
    ])
    return np.tile(one_cycle, repeats)


def generate_p2_low_battery(duration_total_s: float = 12.0) -> np.ndarray:
    """Pattern P2: Continuous rapid beeping (120 ms tone, 120 ms silence)."""
    beep = generate_tone(0.12, BEEP_FREQ)
    gap = generate_silence(0.12)
    cycle = np.concatenate([beep, gap])
    repeats = int(duration_total_s / (0.12 + 0.12))
    return np.tile(cycle, repeats)


def generate_p3_overload(duration_s: float = 10.0) -> np.ndarray:
    """Pattern P3: Continuous steady unbroken tone (> 600 ms)."""
    return generate_tone(duration_s, BEEP_FREQ, amplitude=0.85)


def generate_fan_noise(duration_s: float = 20.0) -> np.ndarray:
    """Generate ambient server hall noise: pink turbulence + 60Hz/120Hz transformer hum."""
    num_samples = int(SAMPLE_RATE * duration_s)
    # White noise
    white = np.random.normal(0.0, 0.25, num_samples)
    # 1st-order IIR filter for pink-ish spectral tilt
    b = [0.049922035, -0.095993537, 0.050612699, -0.004408786]
    a = [1.0, -2.494956002, 2.017265875, -0.522189400]
    import scipy.signal
    try:
        pink = scipy.signal.lfilter(b, a, white)
    except Exception:
        # Fallback moving average filter if scipy is unavailable
        pink = np.convolve(white, np.ones(5) / 5, mode="same")

    # Add 60 Hz and 120 Hz mains hum
    t = np.linspace(0.0, duration_s, num_samples, endpoint=False)
    hum = 0.08 * np.sin(2.0 * np.pi * 60.0 * t) + 0.05 * np.sin(2.0 * np.pi * 120.0 * t)

    noise = pink + hum
    # Normalize to -6 dB
    max_val = np.max(np.abs(noise))
    if max_val > 0:
        noise = (noise / max_val) * 0.5
    return noise


def main() -> None:
    output_dir = Path("beeps")
    output_dir.mkdir(exist_ok=True)

    print("Generating Beacon v2.1 test alarm WAVs at 2500 Hz...")
    save_wav(output_dir / "P1_on_battery.wav", generate_p1_on_battery(repeats=3))
    save_wav(output_dir / "P2_low_battery.wav", generate_p2_low_battery(duration_total_s=12.0))
    save_wav(output_dir / "P3_overload.wav", generate_p3_overload(duration_s=8.0))
    save_wav(output_dir / "datacenter_fan_noise.wav", generate_fan_noise(duration_s=20.0))
    print(f"All WAVs successfully generated in {output_dir.resolve()}/")


if __name__ == "__main__":
    main()

