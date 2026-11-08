# Turns one beep into 19 numbers for the model, plus the two non-ML baselines.
import numpy as np

RACKS = ["A", "B", "C", "D", "E"]
LABELS = RACKS + ["NONE"]
# cm along the row: five 10 cm boxes pressed together (row is 50 cm), mics in front of A, C and E.
# Only the centroid baseline uses these; the ML models learn the layout from the recordings.
RACK_X = {"A": 5.0, "B": 15.0, "C": 25.0, "D": 35.0, "E": 45.0}
MIC_X = [5.0, 25.0, 45.0]          # L, M, R
MIC_RACK = ["A", "C", "E"]         # the rack each mic sits in front of

FEATURE_NAMES = (
    ["log_mean_L", "log_mean_M", "log_mean_R",
     "share_L", "share_M", "share_R",
     "logratio_L/M", "logratio_M/R", "logratio_L/R",
     "log_peak_L", "log_peak_M", "log_peak_R",
     "log_snr_L", "log_snr_M", "log_snr_R",
     "log_purity_L", "log_purity_M", "log_purity_R",
     "duration_ms"]
)
# a rack beep counts only if some mic heard it at least 4x louder than the background;
# quieter ones are a muffled phone or bits of background chatter
MIN_SNR = 4.0

# volume-free features (shares + ratios): what kNN uses
RATIO_IDX = [3, 4, 5, 6, 7, 8]
EPS = 1e-6


def beep_features(beep):
    F = np.array([f[1] for f in beep["frames"]], dtype=float)   # frames x 9
    e = F[:, 0:3]
    side = (F[:, 3:6] + F[:, 6:9]) / 2
    mean = e.mean(axis=0)
    share = mean / max(mean.sum(), EPS)
    logratio = [np.log((mean[0] + EPS) / (mean[1] + EPS)),
                np.log((mean[1] + EPS) / (mean[2] + EPS)),
                np.log((mean[0] + EPS) / (mean[2] + EPS))]
    peak = e.max(axis=0)
    snr = mean / np.maximum(beep["floor"], EPS)
    purity = np.median(e / np.maximum(side, EPS), axis=0)
    duration = (beep["t_end_ms"] - beep["t_start_ms"]) + 16
    return np.concatenate([np.log(mean + EPS), share, logratio, np.log(peak + EPS),
                           np.log(snr + EPS), np.log(purity + EPS), [duration]])


def loudest_mic(features):
    """Baseline 1: the rack in front of the loudest mic. Can only ever say A, C or E."""
    return MIC_RACK[int(np.argmax(features[0:3]))]


def centroid(features, power=1.0):
    """Baseline 2: a position from each mic's share of the loudness, snapped to the nearest rack.
    power > 1 leans harder toward the loudest mic; train.py picks the best power on the training data."""
    w = np.asarray(features[3:6], dtype=float) ** power
    x = float(np.dot(w / max(w.sum(), EPS), MIC_X))
    return min(RACKS, key=lambda r: abs(RACK_X[r] - x))


def is_clear(features):
    return float(np.exp(features[12:15]).max()) >= MIN_SNR
