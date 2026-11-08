#!/usr/bin/env python3
"""Trains and tests the Beacon rack locator.

  python3 tools/train.py                       train on session 1, test on session 2
  python3 tools/train.py --train 1 --test 2
  python3 tools/train.py --train 1             no test session yet: rough cross-validation only

Writes model/locator.joblib (retrained on every session for the live demo) and model/metrics.json.
"""
import argparse
import csv
import glob
import json
import os
import sys

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, confusion_matrix
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
from beacon.detect import BeepDetector                       # noqa: E402
from beacon.features import (FEATURE_NAMES, LABELS, RACKS,   # noqa: E402
                             RATIO_IDX, beep_features, centroid, is_clear, loudest_mic)
from beacon.frames import FIELDS                             # noqa: E402

VOTE = 4   # the live demo votes over this many beeps before locking the laser


def load_session(data_dir, session):
    X, y, files = [], [], []
    for path in sorted(glob.glob(os.path.join(data_dir, f"session{session}_*.csv"))):
        with open(path) as f:
            rows = list(csv.DictReader(f))
        if not rows:
            continue
        label = rows[0]["label"]
        is_none = label == "NONE"
        det = BeepDetector(require_purity=not is_none, min_frames=1 if is_none else 3)
        n = faint = 0
        for r in rows:
            beep = det.push(int(r["pico_ms"]), [float(r[k]) for k in FIELDS])
            if beep:
                feats = beep_features(beep)
                if not is_none and not is_clear(feats):
                    faint += 1
                    continue
                X.append(feats)
                y.append(label)
                files.append(os.path.basename(path))
                n += 1
        note = f" (skipped {faint} faint)" if faint else ""
        print(f"    {os.path.basename(path):<24} {n:3d} {'events' if is_none else 'beeps'}{note}")
    return np.array(X), np.array(y), np.array(files)


def models():
    return {
        "kNN (ratios)": ("ratio", make_pipeline(StandardScaler(),
                                                KNeighborsClassifier(n_neighbors=5, weights="distance"))),
        "random forest (all 19)": ("all", RandomForestClassifier(n_estimators=300, random_state=0)),
    }


def cols(X, which):
    return X[:, RATIO_IDX] if which == "ratio" else X


def show_confusion(y_true, y_pred, labels):
    cm = confusion_matrix(y_true, y_pred, labels=labels)
    print("      predicted: " + " ".join(f"{l:>5}" for l in labels))
    for lab, row in zip(labels, cm):
        print(f"      true {lab:<5}  " + " ".join(f"{v:5d}" for v in row))
    return cm.tolist()


def vote_accuracy(model, X, y, files, which):
    """Accuracy when the last VOTE beeps from the same rack are combined, like the live demo does."""
    hits = total = 0
    for fname in sorted(set(files)):
        idx = np.where((files == fname) & (y != "NONE"))[0]
        if len(idx) < VOTE:
            continue
        proba = model.predict_proba(cols(X[idx], which))
        classes = list(model.classes_)
        for i in range(len(idx) - VOTE + 1):
            guess = classes[int(np.argmax(proba[i:i + VOTE].sum(axis=0)))]
            hits += guess == y[idx[i]]
            total += 1
    return hits / total if total else None


def main():
    ap = argparse.ArgumentParser(description="Train and test the Beacon rack locator")
    ap.add_argument("--train", type=int, default=1)
    ap.add_argument("--test", type=int, default=2)
    ap.add_argument("--data", default=os.path.join(ROOT, "data", "recordings"))
    ap.add_argument("--out", default=os.path.join(ROOT, "model"))
    args = ap.parse_args()

    print(f"Session {args.train} (training):")
    Xtr, ytr, ftr = load_session(args.data, args.train)
    if len(ytr) == 0:
        raise SystemExit("No training beeps found. Record session 1 first (tools/record.py).")
    print(f"Session {args.test} (testing):")
    Xte, yte, fte = load_session(args.data, args.test)
    honest = len(yte) > 0
    present = [l for l in LABELS if l in set(ytr)]
    metrics = {"train_session": args.train, "test_session": args.test if honest else None,
               "train_counts": {l: int((ytr == l).sum()) for l in present}, "methods": {}}

    if honest:
        print(f"\n=== Tested on session {args.test}, which the model never saw ===")
        racks_te = yte != "NONE"
        # give the centroid baseline its best shot: tune its one knob on the training beeps
        racks_tr = ytr != "NONE"
        power = max([1.0, 2.0, 3.0, 4.0],
                    key=lambda p: np.mean([centroid(x, p) == lab for x, lab in zip(Xtr[racks_tr], ytr[racks_tr])]))
        metrics["centroid_power"] = power
        tuned = lambda x: centroid(x, power)  # noqa: E731
        for name, fn in (("loudest mic (baseline)", loudest_mic), (f"weighted centroid (baseline, power {power:g})", tuned)):
            pred = np.array([fn(x) for x in Xte[racks_te]])
            acc = accuracy_score(yte[racks_te], pred)
            print(f"\n  {name}: {acc:.0%} of rack beeps")
            metrics["methods"][name] = {"rack_accuracy": acc,
                                        "confusion": show_confusion(yte[racks_te], pred, RACKS)}
        scores = {}
        for name, (which, model) in models().items():
            model.fit(cols(Xtr, which), ytr)
            pred = model.predict(cols(Xte, which))
            acc = accuracy_score(yte, pred)
            rack_acc = accuracy_score(yte[racks_te], pred[racks_te]) if racks_te.any() else None
            voted = vote_accuracy(model, Xte, yte, fte, which)
            scores[name] = acc
            print(f"\n  {name}: {acc:.0%} of all test events"
                  + (f", {rack_acc:.0%} of rack beeps" if rack_acc is not None else "")
                  + (f", {voted:.0%} with {VOTE}-beep voting" if voted is not None else ""))
            metrics["methods"][name] = {"accuracy": acc, "rack_accuracy": rack_acc, f"vote{VOTE}_accuracy": voted,
                                        "confusion": show_confusion(yte, pred, [l for l in LABELS if l in set(yte) | set(pred)])}
        best = max(scores, key=scores.get)
    else:
        print("\n=== No test session yet: 5-fold cross-validation on the training session (rough, optimistic) ===")
        scores = {}
        for name, (which, model) in models().items():
            k = max(2, min(5, int(min((ytr == l).sum() for l in present))))
            pred = cross_val_predict(model, cols(Xtr, which), ytr, cv=StratifiedKFold(k, shuffle=True, random_state=0))
            scores[name] = accuracy_score(ytr, pred)
            print(f"\n  {name}: {scores[name]:.0%} (cross-validated)")
            metrics["methods"][name] = {"cv_accuracy": scores[name], "confusion": show_confusion(ytr, pred, present)}
        best = max(scores, key=scores.get)
        print("\n  Record session 2 and run this again for the honest number.")

    # the live demo uses the best method, retrained on everything we have
    which, final = models()[best]
    Xall = np.vstack([Xtr, Xte]) if honest else Xtr
    yall = np.concatenate([ytr, yte]) if honest else ytr
    final.fit(cols(Xall, which), yall)
    os.makedirs(args.out, exist_ok=True)
    joblib.dump({"model": final, "name": best, "features": which, "feature_names": FEATURE_NAMES,
                 "labels": list(final.classes_), "vote": VOTE}, os.path.join(args.out, "locator.joblib"))
    metrics["chosen"] = best
    with open(os.path.join(args.out, "metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2, default=float)
    print(f"\nChosen for the live demo: {best} (retrained on {len(yall)} events). "
          f"Saved model/locator.joblib and model/metrics.json")


if __name__ == "__main__":
    main()
