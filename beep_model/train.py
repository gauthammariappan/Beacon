"""Train the alarm-rhythm classifier.

Clips are synthesized from patterns.json, passed through the same beep
detector used at prediction time, and reduced to a few timing features.
A logistic model is fit in an epoch loop. A random forest is fit on the
same features. The one with the higher validation macro-F1 is saved.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import SGDClassifier
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    log_loss,
)
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_sample_weight

from audio import (
    FEATURE_NAMES,
    ROOT,
    SAMPLE_RATE,
    detect_pulses,
    detection_precision,
    detection_recall,
    extract_features,
    load_audio,
    load_catalog,
    synthesize,
    write_wav,
)
from predict import classify_file

ARTIFACTS = ROOT / "artifacts"
REAL_DIR = ROOT / "data" / "real"


def generate(catalog: dict, per_class: int, seed: int):
    rng = np.random.default_rng(seed)
    window_s = float(catalog["window_s"])
    sr = int(catalog["sample_rate"])
    features = []
    labels = []
    recalls = defaultdict(list)
    precisions = defaultdict(list)
    false_alarms = []
    for spec in catalog["classes"]:
        class_id = spec["id"]
        print(f"synthesize {class_id} x{per_class}")
        for _ in range(per_class):
            audio, truth = synthesize(spec, rng, sr, window_s)
            detected = detect_pulses(audio, sr)
            features.append(extract_features(detected, len(audio) / sr))
            labels.append(class_id)
            if spec["kind"] == "negative" and not truth:
                false_alarms.append(0 if not detected else 1)
            else:
                recalls[class_id].append(detection_recall(truth, detected))
                precisions[class_id].append(detection_precision(truth, detected))
    return (
        np.vstack(features),
        np.asarray(labels),
        {key: float(np.mean(values)) for key, values in recalls.items()},
        {key: float(np.mean(values)) for key, values in precisions.items()},
        float(np.mean(false_alarms)) if false_alarms else 0.0,
    )


def stratified_split(labels: np.ndarray, rng: np.random.Generator, fracs=(0.7, 0.15, 0.15)):
    train, val, test = [], [], []
    for class_id in sorted(set(labels.tolist())):
        index = np.flatnonzero(labels == class_id)
        rng.shuffle(index)
        n_train = int(round(fracs[0] * len(index)))
        n_val = int(round(fracs[1] * len(index)))
        train.extend(index[:n_train])
        val.extend(index[n_train : n_train + n_val])
        test.extend(index[n_train + n_val :])
    return (
        np.asarray(train, dtype=int),
        np.asarray(val, dtype=int),
        np.asarray(test, dtype=int),
    )


def fit_sgd(x_train, y_train, x_val, y_val, classes, epochs: int, seed: int):
    scaler = StandardScaler()
    x_train_s = scaler.fit_transform(x_train)
    x_val_s = scaler.transform(x_val)
    weights = compute_sample_weight("balanced", y_train)
    model = SGDClassifier(
        loss="log_loss",
        penalty="l2",
        alpha=1e-4,
        learning_rate="invscaling",
        eta0=0.2,
        power_t=0.5,
        random_state=seed,
        tol=None,
        max_iter=1,
    )
    rng = np.random.default_rng(seed)
    history = []
    best = None
    best_f1 = -1.0
    class_list = list(classes)
    for epoch in range(1, epochs + 1):
        order = rng.permutation(len(x_train_s))
        model.partial_fit(
            x_train_s[order],
            y_train[order],
            classes=class_list if epoch == 1 else None,
            sample_weight=weights[order],
        )
        proba = model.predict_proba(x_train_s)
        train_loss = float(log_loss(y_train, proba, labels=list(model.classes_)))
        val_pred = model.predict(x_val_s)
        val_f1 = float(f1_score(y_val, val_pred, average="macro", labels=class_list))
        history.append({"epoch": epoch, "train_logloss": train_loss, "val_macro_f1": val_f1})
        print(f"epoch {epoch:02d}  train_logloss {train_loss:.4f}  val_macro_f1 {val_f1:.4f}")
        if val_f1 > best_f1:
            best_f1 = val_f1
            best = deepcopy(model)
    return best, scaler, best_f1, history


def fit_forest(x_train, y_train, x_val, y_val, classes, seed: int):
    model = RandomForestClassifier(
        n_estimators=400,
        max_depth=18,
        min_samples_leaf=2,
        class_weight="balanced_subsample",
        random_state=seed,
        n_jobs=-1,
    )
    model.fit(x_train, y_train)
    val_f1 = float(
        f1_score(y_val, model.predict(x_val), average="macro", labels=list(classes))
    )
    print(f"random forest  val_macro_f1 {val_f1:.4f}")
    return model, val_f1


def evaluate(model, scaler, features, labels, classes) -> dict:
    matrix_x = scaler.transform(features) if scaler is not None else features
    predicted = model.predict(matrix_x)
    report = classification_report(
        labels,
        predicted,
        labels=list(classes),
        output_dict=True,
        zero_division=0,
    )
    matrix = confusion_matrix(labels, predicted, labels=list(classes))
    return {
        "accuracy": float(accuracy_score(labels, predicted)),
        "macro_f1": float(f1_score(labels, predicted, average="macro", labels=list(classes))),
        "per_class_f1": {name: float(report[name]["f1-score"]) for name in classes},
        "confusion_matrix": {
            "labels": list(classes),
            "rows_are_true": matrix.tolist(),
        },
    }


def class_centroids(features, labels, classes) -> dict:
    centroids = {}
    for class_id in classes:
        rows = features[labels == class_id]
        centroids[class_id] = {
            name: float(value) for name, value in zip(FEATURE_NAMES, rows.mean(axis=0))
        }
    return centroids


def save_examples(catalog: dict, bundle_path: Path, seed: int) -> list[dict]:
    rng = np.random.default_rng(seed)
    folder = ARTIFACTS / "examples"
    folder.mkdir(parents=True, exist_ok=True)
    window_s = float(catalog["window_s"])
    sr = int(catalog["sample_rate"])
    results = []
    for spec in catalog["classes"]:
        audio, _truth = synthesize(spec, rng, sr, window_s)
        path = folder / f"{spec['id']}.wav"
        write_wav(path, audio, sr)
        result = classify_file(path, joblib.load(bundle_path))
        result["expected"] = spec["id"]
        result["match"] = result["rhythm"] == spec["id"]
        results.append(
            {
                "file": path.name,
                "expected": spec["id"],
                "predicted": result["rhythm"],
                "confidence": result["confidence"],
                "match": result["match"],
            }
        )
        mark = "ok" if result["match"] else "MISS"
        print(f"example {mark:4}  {spec['id']} -> {result['rhythm']} ({result['confidence']:.2f})")
    return results


def exam_real(bundle_path: Path) -> list[dict]:
    sources_path = REAL_DIR / "sources.json"
    if not sources_path.exists():
        print("no real recordings catalog")
        return []
    catalog = json.loads(sources_path.read_text(encoding="utf-8"))
    bundle = joblib.load(bundle_path)
    rows = []
    for item in catalog["files"]:
        path = REAL_DIR / item["file"]
        if not path.exists():
            print(f"missing {path.name}")
            continue
        audio, sr = load_audio(path, SAMPLE_RATE)
        result = classify_file(path, bundle)
        row = {
            "file": item["file"],
            "expected": item["expected"],
            "predicted": result["rhythm"],
            "confidence": result["confidence"],
            "confident": result["confident"],
            "match": result["rhythm"] == item["expected"],
            "duration_s": result["duration_s"],
            "n_pulses": result["n_pulses"],
            "top": result["top"],
        }
        rows.append(row)
        mark = "ok" if row["match"] else "MISS"
        print(
            f"real {mark:4}  {item['file']} -> {result['rhythm']} "
            f"({result['confidence']:.2f}, expected {item['expected']}, pulses {result['n_pulses']})"
        )
    return rows


def print_matrix(metrics: dict) -> None:
    labels = metrics["confusion_matrix"]["labels"]
    rows = metrics["confusion_matrix"]["rows_are_true"]
    short = [label.replace("pulse_every_", "p").replace("_beep", "")[:18] for label in labels]
    header = " ".join(f"{name:>18}" for name in short)
    print(f"{'true':>18} {header}")
    for label, row, name in zip(labels, rows, short):
        cells = " ".join(f"{value:18d}" for value in row)
        print(f"{name:>18} {cells}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the UPS alarm-rhythm model.")
    parser.add_argument("--per-class", type=int, default=400)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    catalog = load_catalog()
    # Lexicographic order matches what sklearn expects for probability columns.
    classes = sorted(spec["id"] for spec in catalog["classes"])
    features, labels, recall, precision, false_alarm_rate = generate(catalog, args.per_class, args.seed)
    print("\ndetector recall / precision (precision falls if a beep is swallowed into a long blob)")
    for class_id in classes:
        if class_id in recall:
            print(f"  {class_id:24} {recall[class_id]:.3f}  {precision.get(class_id, 0):.3f}")
    print(f"  noise false-alarm rate   {false_alarm_rate:.3f}")
    weak = [name for name, score in recall.items() if score < 0.8]
    weak += [name for name, score in precision.items() if score < 0.6 and name not in weak]
    if weak:
        print("WARNING: detector recall is below 0.8 for: " + ", ".join(weak))

    split_rng = np.random.default_rng(args.seed + 1)
    train_i, val_i, test_i = stratified_split(labels, split_rng)
    print(
        f"\nsplit  train {len(train_i)}  val {len(val_i)}  test {len(test_i)}  "
        f"features {features.shape[1]}"
    )

    print("\nlogistic regression, one pass per epoch")
    sgd, scaler, sgd_f1, history = fit_sgd(
        features[train_i],
        labels[train_i],
        features[val_i],
        labels[val_i],
        classes,
        args.epochs,
        args.seed,
    )
    print("\nrandom forest")
    forest, forest_f1 = fit_forest(
        features[train_i],
        labels[train_i],
        features[val_i],
        labels[val_i],
        classes,
        args.seed,
    )

    if forest_f1 >= sgd_f1:
        chosen_name = "random_forest"
        chosen = forest
        chosen_scaler = None
        chosen_f1 = forest_f1
    else:
        chosen_name = "sgd_log"
        chosen = sgd
        chosen_scaler = scaler
        chosen_f1 = sgd_f1
    print(f"\nselected {chosen_name}  val_macro_f1 {chosen_f1:.4f}")

    test_metrics = evaluate(chosen, chosen_scaler, features[test_i], labels[test_i], classes)
    print(
        f"test accuracy {test_metrics['accuracy']:.4f}  "
        f"test macro_f1 {test_metrics['macro_f1']:.4f}"
    )
    print_matrix(test_metrics)

    meanings = {spec["id"]: spec["meanings"] for spec in catalog["classes"]}
    sources = {spec["id"]: spec.get("sources", []) for spec in catalog["classes"]}
    bundle = {
        "model": chosen,
        "scaler": chosen_scaler,
        "model_name": chosen_name,
        "classes": classes,
        "feature_names": FEATURE_NAMES,
        "sample_rate": SAMPLE_RATE,
        "low_confidence": float(catalog["low_confidence"]),
        "meanings": meanings,
        "sources": sources,
    }
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    bundle_path = ARTIFACTS / "model.joblib"
    joblib.dump(bundle, bundle_path)

    importances = {
        name: float(value)
        for name, value in zip(FEATURE_NAMES, forest.feature_importances_)
    }
    print("\nexample clips")
    examples = save_examples(catalog, bundle_path, args.seed + 99)
    print("\nheld-out manufacturer recordings")
    real_rows = exam_real(bundle_path)

    metrics = {
        "model_name": chosen_name,
        "per_class": args.per_class,
        "seed": args.seed,
        "epochs": args.epochs,
        "n_train": int(len(train_i)),
        "n_val": int(len(val_i)),
        "n_test": int(len(test_i)),
        "feature_names": FEATURE_NAMES,
        "detector_recall": recall,
        "detector_precision": precision,
        "noise_false_alarm_rate": false_alarm_rate,
        "val_macro_f1": {"sgd_log": sgd_f1, "random_forest": forest_f1},
        "selected_val_macro_f1": chosen_f1,
        "sgd_history": history,
        "test": test_metrics,
        "random_forest_feature_importance": importances,
        "test_feature_centroids": class_centroids(features[test_i], labels[test_i], classes),
        "examples": examples,
        "real_exam": real_rows,
    }
    metrics_path = ARTIFACTS / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    np.savez_compressed(ARTIFACTS / "features.npz", X=features, y=labels)
    print(f"\nsaved {bundle_path}")
    print(f"saved {metrics_path}")


if __name__ == "__main__":
    main()
