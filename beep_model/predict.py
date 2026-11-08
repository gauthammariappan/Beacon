"""Classify one WAV with the saved alarm-rhythm model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np

from audio import ROOT, detect_pulses, extract_features, load_audio

BUNDLE_PATH = ROOT / "artifacts" / "model.joblib"


def load_bundle(path: Path | None = None):
    bundle_path = path or BUNDLE_PATH
    if not bundle_path.exists():
        raise SystemExit(f"No trained model at {bundle_path}. Run train.py first.")
    return joblib.load(bundle_path)


def classify_audio(audio: np.ndarray, sr: int, bundle: dict) -> dict:
    pulses = detect_pulses(audio, sr)
    duration = len(audio) / sr
    features = extract_features(pulses, duration).reshape(1, -1)
    scaler = bundle.get("scaler")
    if scaler is not None:
        features = scaler.transform(features)
    model = bundle["model"]
    probabilities = model.predict_proba(features)[0]
    classes = list(model.classes_)
    order = np.argsort(probabilities)[::-1]
    top = [
        {"rhythm": classes[index], "p": float(probabilities[index])}
        for index in order[:3]
    ]
    best = top[0]
    meanings = bundle.get("meanings", {}).get(best["rhythm"], [])
    return {
        "rhythm": best["rhythm"],
        "confidence": best["p"],
        "confident": bool(best["p"] >= bundle.get("low_confidence", 0.55)),
        "meanings": meanings,
        "top": top,
        "duration_s": round(duration, 3),
        "n_pulses": len(pulses),
        "pulses_s": [[round(start, 3), round(end, 3)] for start, end in pulses[:12]],
    }


def classify_file(path: str | Path, bundle: dict | None = None) -> dict:
    bundle = bundle or load_bundle()
    audio, sr = load_audio(path, bundle["sample_rate"])
    result = classify_audio(audio, sr, bundle)
    result["file"] = str(path)
    return result


def format_result(result: dict) -> str:
    lines = [
        f"file: {result.get('file', '')}",
        f"rhythm: {result['rhythm']}",
        f"confidence: {result['confidence']:.3f}",
        f"confident: {result['confident']}",
        f"duration_s: {result['duration_s']}",
        f"pulses: {result['n_pulses']}",
    ]
    if result["meanings"]:
        lines.append("meanings:")
        for meaning in result["meanings"]:
            lines.append(f"  - {meaning}")
    lines.append("top:")
    for item in result["top"]:
        lines.append(f"  {item['p']:.3f}  {item['rhythm']}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify a beep recording.")
    parser.add_argument("wav", type=Path)
    parser.add_argument("--model", type=Path, default=BUNDLE_PATH)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = classify_file(args.wav, load_bundle(args.model))
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_result(result))


if __name__ == "__main__":
    main()
