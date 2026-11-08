"""Spatial feature extraction for Beacon v2.1 acoustic localization."""

from __future__ import annotations

from typing import Any
import numpy as np


def extract_spatial_features(
    active_frames: list[dict[str, Any]],
    noise_floor: np.ndarray | list[float] | float,
) -> np.ndarray:
    """Extract spatial features from active beep frames.

    Parameters
    ----------
    active_frames : list[dict]
        List of frame dictionaries. Each dict contains energy measurements across
        microphones:
          - L25, M25, R25 (or array under key 'e2500'): energies at 2500 Hz
          - L20, M20, R20 (or array under key 'e2000'): energies at 2000 Hz
          - L30, M30, R30 (or array under key 'e3000'): energies at 3000 Hz
          - 'ms' (or 'timestamp'): timestamp in milliseconds
          - optional 'purity': pre-computed purity array/list [p_L, p_M, p_R]
    noise_floor : np.ndarray | list[float] | float
        Baseline noise floor at 2500 Hz for [Left, Middle, Right] microphones.
        If a scalar is provided, it is broadcast to all three channels.

    Returns
    -------
    np.ndarray
        A flat 19-element 1D numpy array of dtype float64:
          [0:3]   3 average 2500Hz energies (Left, Middle, Right)
          [3:6]   3 shares (each / total 2500Hz average energy)
          [6:9]   3 log ratios (log(L/M), log(M/R), log(L/R))
          [9:12]  3 peak energies (Left, Middle, Right)
          [12:15] 3 SNRs in dB (10 * log10(avg_energy / noise_floor))
          [15:18] 3 average purities (Left, Middle, Right)
          [18]    1 duration in ms
    """
    eps = 1e-9

    # Prepare noise floor array
    nf = np.asarray(noise_floor, dtype=np.float64)
    if nf.ndim == 0:
        nf = np.full(3, float(nf), dtype=np.float64)
    elif nf.shape != (3,):
        nf = np.resize(nf, 3).astype(np.float64)

    # Handle empty frame sequence
    if not active_frames:
        return np.zeros(19, dtype=np.float64)

    n_frames = len(active_frames)

    # 1. Extract 2500Hz energies (N, 3)
    first_frame = active_frames[0]
    if "e2500" in first_frame:
        e2500_all = np.array([f["e2500"] for f in active_frames], dtype=np.float64)
    else:
        e2500_all = np.array(
            [[f["L25"], f["M25"], f["R25"]] for f in active_frames],
            dtype=np.float64,
        )

    # Ensure shape (N, 3)
    if e2500_all.ndim == 1:
        e2500_all = e2500_all.reshape(1, -1)

    # 2. Extract 2000Hz and 3000Hz energies for purity calculation (if needed)
    if "e2000" in first_frame and "e3000" in first_frame:
        e2000_all = np.array([f["e2000"] for f in active_frames], dtype=np.float64)
        e3000_all = np.array([f["e3000"] for f in active_frames], dtype=np.float64)
    elif "L20" in first_frame and "L30" in first_frame:
        e2000_all = np.array(
            [[f["L20"], f["M20"], f["R20"]] for f in active_frames],
            dtype=np.float64,
        )
        e3000_all = np.array(
            [[f["L30"], f["M30"], f["R30"]] for f in active_frames],
            dtype=np.float64,
        )
    else:
        e2000_all = None
        e3000_all = None

    # [1] 3 average 2500Hz energies (raw)
    avg_2500 = np.mean(e2500_all, axis=0)  # shape (3,)

    # Hardware gain normalization via frozen noise floor:
    # normalized_energy = avg_2500 / np.maximum(noise_floor, 1e-6)
    safe_nf = np.maximum(nf, 1e-6)
    normalized_energy = avg_2500 / safe_nf

    # [2] 3 shares computed using normalized_energy instead of raw energy
    total_norm = float(np.sum(normalized_energy))
    if total_norm > eps:
        shares = normalized_energy / total_norm
    else:
        shares = np.full(3, 1.0 / 3.0, dtype=np.float64)

    # [3] 3 log ratios using normalized_energy: [log(norm_L/norm_M), log(norm_M/norm_R), log(norm_L/norm_R)]
    safe_norm = np.maximum(normalized_energy, 1e-6)
    log_lm = float(np.log(safe_norm[0] / safe_norm[1]))
    log_mr = float(np.log(safe_norm[1] / safe_norm[2]))
    log_lr = float(np.log(safe_norm[0] / safe_norm[2]))
    log_ratios = np.clip(np.array([log_lm, log_mr, log_lr], dtype=np.float64), -10.0, 10.0)

    # [4] 3 peak energies (raw)
    peak_energies = np.max(e2500_all, axis=0)  # shape (3,)

    # [5] 3 SNRs in dB: 10 * log10(avg_energy / noise_floor)
    snr_db = 10.0 * np.log10(np.maximum(avg_2500, eps) / safe_nf)

    # [6] 3 average purities: e2500 / avg(e2000, e3000)
    if e2000_all is not None and e3000_all is not None:
        if e2000_all.ndim == 1:
            e2000_all = e2000_all.reshape(1, -1)
        if e3000_all.ndim == 1:
            e3000_all = e3000_all.reshape(1, -1)
        sideband_avg = 0.5 * (e2000_all + e3000_all)
        safe_sideband = np.maximum(sideband_avg, eps)
        purities_all = np.where(e2500_all == 0.0, 0.0, e2500_all / safe_sideband)
        avg_purities = np.mean(purities_all, axis=0)
    elif "purity" in first_frame:
        purities_all = np.array([f["purity"] for f in active_frames], dtype=np.float64)
        if purities_all.ndim == 1:
            purities_all = purities_all.reshape(1, -1)
        avg_purities = np.mean(purities_all, axis=0)
    else:
        avg_purities = np.zeros(3, dtype=np.float64)

    # [7] 1 duration in ms
    last_frame = active_frames[-1]
    t0 = first_frame.get("t_ms", first_frame.get("ms", first_frame.get("timestamp", None)))
    t1 = last_frame.get("t_ms", last_frame.get("ms", last_frame.get("timestamp", None)))
    if t0 is not None and t1 is not None:
        duration_ms = float(t1 - t0)
    else:
        # 50 Hz serial stream implies 20 ms per frame
        duration_ms = float(n_frames * 20.0)

    # Concatenate into flat 19-element numpy array
    features = np.concatenate(
        [
            avg_2500,  # 3 elements (0, 1, 2)
            shares,  # 3 elements (3, 4, 5)
            log_ratios,  # 3 elements (6, 7, 8)
            peak_energies,  # 3 elements (9, 10, 11)
            snr_db,  # 3 elements (12, 13, 14)
            avg_purities,  # 3 elements (15, 16, 17)
            np.array([duration_ms], dtype=np.float64),  # 1 element  (18)
        ],
        dtype=np.float64,
    )

    return features
