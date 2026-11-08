"""Train and evaluate Beacon v2.1 spatial location models against baselines."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any
import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, confusion_matrix
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from beacon.signal import SignalProcessor

CLASSES = ["A", "B", "C", "D", "E", "NONE"]
FEATURE_NAMES = [
    "avg_2500_L", "avg_2500_M", "avg_2500_R",
    "share_L", "share_M", "share_R",
    "log_ratio_LM", "log_ratio_MR", "log_ratio_LR",
    "peak_L", "peak_M", "peak_R",
    "snr_db_L", "snr_db_M", "snr_db_R",
    "purity_L", "purity_M", "purity_R",
    "duration_ms",
]


def predict_loudest_mic(X: np.ndarray) -> np.ndarray:
    """Baseline 1: Loudest mic mapped to A, C, E (fails on B, D, NONE).

    L is mic 0 -> 'A'
    M is mic 1 -> 'C'
    R is mic 2 -> 'E'
    """
    X_arr = np.asarray(X, dtype=np.float64)
    # Features 0:3 are the average 2500Hz energies [L, M, R]
    energies = X_arr[:, 0:3]
    argmax_indices = np.argmax(energies, axis=1)
    mapping = np.array(["A", "C", "E"])
    return mapping[argmax_indices]


def predict_weighted_centroid(X: np.ndarray) -> np.ndarray:
    """Baseline 2: Weighted centroid using normalized shares along 0=A to 4=E.

    Interpolates continuous position:
      x = share_L * 0.0 + share_M * 2.0 + share_R * 4.0
    Snaps to nearest rack: round(x) clipped to [0, 4] -> A, B, C, D, E.
    """
    X_arr = np.asarray(X, dtype=np.float64)
    # Features 3:6 are the shares [share_L, share_M, share_R]
    shares = X_arr[:, 3:6]
    total_shares = np.sum(shares, axis=1, keepdims=True)
    norm_shares = np.where(total_shares > 1e-9, shares / total_shares, 1.0 / 3.0)

    # Positions: A=0, C=2, E=4
    pos = norm_shares[:, 0] * 0.0 + norm_shares[:, 1] * 2.0 + norm_shares[:, 2] * 4.0
    rack_indices = np.clip(np.round(pos).astype(int), 0, 4)
    mapping = np.array(["A", "B", "C", "D", "E"])
    return mapping[rack_indices]


def load_dataset_from_csv(
    csv_path: Path | str,
    processor: SignalProcessor | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Parse serial lines from recording CSV using SignalProcessor to extract 19 features.

    Parameters
    ----------
    csv_path : Path | str
        Path to session recording CSV.
    processor : SignalProcessor, optional
        Processor instance, or new instance if None.

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        X: (N, 19) float features array
        y: (N,) string label array
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Recording CSV not found at: {path}")

    sp = processor or SignalProcessor(alpha=0.02, initial_noise_floor=[10.0, 10.0, 10.0])

    X_list: list[np.ndarray] = []
    y_list: list[str] = []

    current_label = "NONE"

    with open(path, mode="r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue

            # Strip all cells
            cells = [c.strip() for c in row if c.strip()]
            if not cells:
                continue

            # Skip header row
            if cells[0].lower() in ("session", "rack", "label", "target"):
                continue

            line_str = ""
            label_candidate = ""

            # Check if one of the cells contains 'E,' (quoted serial line)
            for c in cells:
                if c.startswith("E,"):
                    line_str = c
                    break

            if line_str:
                # Find label in remaining cells
                for c in cells:
                    if c != line_str and c in CLASSES:
                        label_candidate = c
                        break
            else:
                # Check for unquoted 'E' token
                e_idx = -1
                for i, c in enumerate(cells):
                    if c.upper() == "E":
                        e_idx = i
                        break

                if e_idx >= 0:
                    line_str = ",".join(cells[e_idx:])
                    if e_idx > 0 and cells[e_idx - 1] in CLASSES:
                        label_candidate = cells[e_idx - 1]
                else:
                    # Check if first or last cell is rack label and rest is numbers
                    if cells[0] in CLASSES:
                        label_candidate = cells[0]
                        line_str = f"E,{','.join(cells[1:])}"
                    elif cells[-1] in CLASSES:
                        label_candidate = cells[-1]
                        line_str = f"E,{','.join(cells[:-1])}"
                    elif len(cells) >= 12 and cells[1] in CLASSES:
                        label_candidate = cells[1]
                        line_str = f"E,{','.join(cells[2:])}"

            if label_candidate and label_candidate in CLASSES:
                if label_candidate != current_label and sp.is_beep_active:
                    sp.reset()
                current_label = label_candidate

            if not line_str:
                continue

            event = sp.process_line(line_str)
            if event is not None:
                feat = event.features
                if feat is not None and len(feat) == 19:
                    X_list.append(feat)
                    y_list.append(current_label)

    if not X_list:
        return np.zeros((0, 19), dtype=np.float64), np.array([], dtype=object)

    X = np.vstack(X_list).astype(np.float64)
    y = np.asarray(y_list, dtype=object)
    return X, y


def generate_synthetic_recordings(
    output_dir: Path | str = "recordings",
    seed: int = 42,
) -> tuple[Path, Path]:
    """Generate realistic session1_train.csv and session2_test.csv.

    Follows Beacon architecture specification:
    - 5 racks (A, B, C, D, E) and NONE class
    - Session 1: ~40 beeps per rack + ~40 NONE
    - Session 2: ~25 beeps per rack + ~25 NONE with varied volume and angles
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    session1_path = out_dir / "session1_train.csv"
    session2_path = out_dir / "session2_test.csv"

    rng = np.random.default_rng(seed)

    # Base shares for racks
    rack_profiles = {
        "A": np.array([0.65, 0.25, 0.10]),
        "B": np.array([0.46, 0.46, 0.08]),
        "C": np.array([0.22, 0.56, 0.22]),
        "D": np.array([0.08, 0.46, 0.46]),
        "E": np.array([0.10, 0.25, 0.65]),
    }

    def generate_session_csv(path: Path, session_id: int, beeps_per_class: int, test_mode: bool):
        lines: list[list[str]] = [["session", "rack", "line"]]
        t_ms = 1000

        for rack in ["A", "B", "C", "D", "E"]:
            base_share = rack_profiles[rack]
            for _ in range(beeps_per_class):
                # 1. Quiet baseline frames (10 frames = 200 ms)
                for _ in range(10):
                    t_ms += 20
                    e25 = 10.0 + rng.normal(0, 0.3, 3)
                    e20 = 10.0 + rng.normal(0, 0.3, 3)
                    e30 = 10.0 + rng.normal(0, 0.3, 3)
                    line_data = f"E,{t_ms},{e25[0]:.1f},{e25[1]:.1f},{e25[2]:.1f},{e20[0]:.1f},{e20[1]:.1f},{e20[2]:.1f},{e30[0]:.1f},{e30[1]:.1f},{e30[2]:.1f}"
                    lines.append([str(session_id), rack, line_data])

                # 2. Beep frames (5 to 10 frames, ~100 to 200 ms)
                beep_len = int(rng.integers(5, 11))
                total_energy = float(rng.uniform(200.0, 450.0))
                if test_mode:
                    # In session 2, vary phone volume and position perturbation
                    total_energy *= float(rng.uniform(0.7, 1.4))
                    share_jitter = rng.normal(0, 0.04, 3)
                else:
                    share_jitter = rng.normal(0, 0.02, 3)

                shares = np.maximum(base_share + share_jitter, 0.02)
                shares = shares / np.sum(shares)

                for _ in range(beep_len):
                    t_ms += 20
                    e25 = total_energy * shares + rng.normal(0, 1.0, 3)
                    # Sidebands stay low background for pure beep
                    e20 = 10.0 + rng.normal(0, 0.5, 3)
                    e30 = 10.0 + rng.normal(0, 0.5, 3)
                    line_data = f"E,{t_ms},{e25[0]:.1f},{e25[1]:.1f},{e25[2]:.1f},{e20[0]:.1f},{e20[1]:.1f},{e20[2]:.1f},{e30[0]:.1f},{e30[1]:.1f},{e30[2]:.1f}"
                    lines.append([str(session_id), rack, line_data])

                # 3. Trailing quiet frames to confirm beep end (3 frames = 60 ms)
                for _ in range(3):
                    t_ms += 20
                    e25 = 10.0 + rng.normal(0, 0.3, 3)
                    e20 = 10.0 + rng.normal(0, 0.3, 3)
                    e30 = 10.0 + rng.normal(0, 0.3, 3)
                    line_data = f"E,{t_ms},{e25[0]:.1f},{e25[1]:.1f},{e25[2]:.1f},{e20[0]:.1f},{e20[1]:.1f},{e20[2]:.1f},{e30[0]:.1f},{e30[1]:.1f},{e30[2]:.1f}"
                    lines.append([str(session_id), rack, line_data])

        # NONE class: claps, table bumps, environmental noise spikes
        for _ in range(beeps_per_class):
            for _ in range(10):
                t_ms += 20
                e25 = 10.0 + rng.normal(0, 0.3, 3)
                e20 = 10.0 + rng.normal(0, 0.3, 3)
                e30 = 10.0 + rng.normal(0, 0.3, 3)
                line_data = f"E,{t_ms},{e25[0]:.1f},{e25[1]:.1f},{e25[2]:.1f},{e20[0]:.1f},{e20[1]:.1f},{e20[2]:.1f},{e30[0]:.1f},{e30[1]:.1f},{e30[2]:.1f}"
                lines.append([str(session_id), "NONE", line_data])

            # Claps or bumps produce loud sound (> 5x floor) with lower purity (2.6 - 3.5) and diffuse shares
            noise_len = int(rng.integers(3, 7))
            noise_energy = float(rng.uniform(120.0, 260.0))
            # Random diffuse shares across microphones (no sharp single-rack focus)
            random_shares = rng.uniform(0.25, 0.45, 3)
            random_shares = random_shares / np.sum(random_shares)

            for _ in range(noise_len):
                t_ms += 20
                e25 = noise_energy * random_shares + rng.normal(0, 1.5, 3)
                # Broad spectrum: sidebands are significant so purity is close to threshold (2.6 to 3.8)
                side_energy = e25 / float(rng.uniform(2.7, 3.8))
                e20 = side_energy + rng.normal(0, 1.0, 3)
                e30 = side_energy + rng.normal(0, 1.0, 3)

                line_data = f"E,{t_ms},{e25[0]:.1f},{e25[1]:.1f},{e25[2]:.1f},{e20[0]:.1f},{e20[1]:.1f},{e20[2]:.1f},{e30[0]:.1f},{e30[1]:.1f},{e30[2]:.1f}"
                lines.append([str(session_id), "NONE", line_data])

            for _ in range(3):
                t_ms += 20
                e25 = 10.0 + rng.normal(0, 0.3, 3)
                e20 = 10.0 + rng.normal(0, 0.3, 3)
                e30 = 10.0 + rng.normal(0, 0.3, 3)
                line_data = f"E,{t_ms},{e25[0]:.1f},{e25[1]:.1f},{e25[2]:.1f},{e20[0]:.1f},{e20[1]:.1f},{e20[2]:.1f},{e30[0]:.1f},{e30[1]:.1f},{e30[2]:.1f}"
                lines.append([str(session_id), "NONE", line_data])

        with open(path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerows(lines)

    generate_session_csv(session1_path, session_id=1, beeps_per_class=40, test_mode=False)
    generate_session_csv(session2_path, session_id=2, beeps_per_class=25, test_mode=True)
    return session1_path, session2_path


def train_and_evaluate(
    train_csv: Path | str,
    test_csv: Path | str,
    model_out: Path | str = "artifacts/location_model.joblib",
    metrics_out: Path | str = "artifacts/location_metrics.json",
    seed: int = 42,
) -> dict[str, Any]:
    """Train RandomForest and kNN models on Session 1, evaluate against baselines on Session 2.

    Parameters
    ----------
    train_csv : Path | str
        Path to recordings/session1_train.csv.
    test_csv : Path | str
        Path to recordings/session2_test.csv.
    model_out : Path | str
        Path to save winning joblib model.
    metrics_out : Path | str
        Path to save metrics JSON.
    seed : int
        Random seed for reproducibility.

    Returns
    -------
    dict[str, Any]
        Dictionary of evaluated metrics for all methods.
    """
    train_path = Path(train_csv)
    test_path = Path(test_csv)
    model_out_path = Path(model_out)
    metrics_out_path = Path(metrics_out)

    model_out_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Loading training data from {train_path}...")
    X_train, y_train = load_dataset_from_csv(train_path)
    print(f"Loaded {len(X_train)} training events. Classes distribution:")
    for cls in CLASSES:
        print(f"  {cls}: {np.sum(y_train == cls)}")

    print(f"\nLoading test data from {test_path}...")
    X_test, y_test = load_dataset_from_csv(test_path)
    print(f"Loaded {len(X_test)} test events. Classes distribution:")
    for cls in CLASSES:
        print(f"  {cls}: {np.sum(y_test == cls)}")

    if len(X_train) == 0 or len(X_test) == 0:
        raise RuntimeError("No events extracted from CSV datasets.")

    # 1. Evaluate Baseline 1: Loudest Mic
    y_pred_loudest = predict_loudest_mic(X_test)
    acc_loudest = float(accuracy_score(y_test, y_pred_loudest))
    cm_loudest = confusion_matrix(y_test, y_pred_loudest, labels=CLASSES).tolist()
    print(f"\n[Baseline 1] Loudest Mic Accuracy: {acc_loudest * 100:.2f}%")

    # 2. Evaluate Baseline 2: Weighted Centroid
    y_pred_centroid = predict_weighted_centroid(X_test)
    acc_centroid = float(accuracy_score(y_test, y_pred_centroid))
    cm_centroid = confusion_matrix(y_test, y_pred_centroid, labels=CLASSES).tolist()
    print(f"[Baseline 2] Weighted Centroid Accuracy: {acc_centroid * 100:.2f}%")

    # 3. Train and Evaluate Random Forest Classifier
    rf = RandomForestClassifier(
        n_estimators=100,
        max_depth=12,
        min_samples_split=2,
        random_state=seed,
    )
    rf.fit(X_train, y_train)
    y_pred_rf = rf.predict(X_test)
    acc_rf = float(accuracy_score(y_test, y_pred_rf))
    cm_rf = confusion_matrix(y_test, y_pred_rf, labels=CLASSES).tolist()
    print(f"[ML Model 1] Random Forest Accuracy: {acc_rf * 100:.2f}%")

    # 4. Train and Evaluate kNN Classifier
    knn_pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("knn", KNeighborsClassifier(n_neighbors=5, weights="distance")),
    ])
    knn_pipe.fit(X_train, y_train)
    y_pred_knn = knn_pipe.predict(X_test)
    acc_knn = float(accuracy_score(y_test, y_pred_knn))
    cm_knn = confusion_matrix(y_test, y_pred_knn, labels=CLASSES).tolist()
    print(f"[ML Model 2] kNN Accuracy: {acc_knn * 100:.2f}%")

    # Determine winning ML model
    if acc_rf >= acc_knn:
        winning_name = "random_forest"
        winning_model = rf
        winning_scaler = None
        winning_acc = acc_rf
    else:
        winning_name = "knn"
        winning_model = knn_pipe.named_steps["knn"]
        winning_scaler = knn_pipe.named_steps["scaler"]
        winning_acc = acc_knn

    print(f"\nWinning ML Model: {winning_name} ({winning_acc * 100:.2f}%)")

    # Save winning model bundle
    bundle = {
        "model": winning_model,
        "model_name": winning_name,
        "scaler": winning_scaler,
        "classes": CLASSES,
        "feature_names": FEATURE_NAMES,
        "accuracy": winning_acc,
    }
    joblib.dump(bundle, model_out_path)
    print(f"Saved winning model to {model_out_path}")

    # Build metrics dict for all 3 methods (+ knn)
    metrics_data = {
        "classes": CLASSES,
        "feature_names": FEATURE_NAMES,
        "loudest_mic": {
            "accuracy": acc_loudest,
            "confusion_matrix": cm_loudest,
        },
        "weighted_centroid": {
            "accuracy": acc_centroid,
            "confusion_matrix": cm_centroid,
        },
        "random_forest": {
            "accuracy": acc_rf,
            "confusion_matrix": cm_rf,
        },
        "knn": {
            "accuracy": acc_knn,
            "confusion_matrix": cm_knn,
        },
        "winning_model": winning_name,
        "winning_accuracy": winning_acc,
    }

    with open(metrics_out_path, mode="w", encoding="utf-8") as f:
        json.dump(metrics_data, f, indent=2)
    print(f"Dumped metrics to {metrics_out_path}")

    return metrics_data


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Beacon v2.1 Spatial Location Model.")
    parser.add_argument("--train-csv", type=Path, default=Path("recordings/session1_train.csv"))
    parser.add_argument("--test-csv", type=Path, default=Path("recordings/session2_test.csv"))
    parser.add_argument("--model-out", type=Path, default=Path("artifacts/location_model.joblib"))
    parser.add_argument("--metrics-out", type=Path, default=Path("artifacts/location_metrics.json"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--generate", action="store_true", help="Force regenerate synthetic data")
    args = parser.parse_args()

    # Generate synthetic recordings if files are missing or requested
    if args.generate or not args.train_csv.exists() or not args.test_csv.exists():
        print("Recordings not found or --generate requested. Generating synthetic sessions...")
        generate_synthetic_recordings(output_dir="recordings", seed=args.seed)

    train_and_evaluate(
        train_csv=args.train_csv,
        test_csv=args.test_csv,
        model_out=args.model_out,
        metrics_out=args.metrics_out,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
