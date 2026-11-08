"""Brain 1: Spatial Location Classifier for Beacon v2.1."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import joblib
import numpy as np

DEFAULT_MODEL_PATH = Path("artifacts/location_model.joblib")
CLASSES_DEFAULT = ["A", "B", "C", "D", "E", "NONE"]


class LocationClassifier:
    """Classifies acoustic beep location into Racks A, B, C, D, E, or NONE.

    Attributes
    ----------
    model : Any
        Trained scikit-learn classifier (e.g. RandomForestClassifier).
    scaler : Any | None
        Optional feature scaler (e.g. StandardScaler).
    classes : list[str]
        Class labels corresponding to output probabilities.
    alpha : float
        Exponential smoothing factor for running vote across consecutive beeps.
    uncertainty_threshold : float
        Probability threshold below which prediction is marked 'uncertain' (default: 0.60).
    running_vote : np.ndarray | None
        Smoothed probability vector across consecutive beeps.
    beeps_count : int
        Number of consecutive beeps integrated into current running vote.
    """

    def __init__(
        self,
        model_path: Path | str | None = None,
        alpha: float = 0.3,
        uncertainty_threshold: float = 0.60,
    ) -> None:
        self.alpha: float = float(alpha)
        self.uncertainty_threshold: float = float(uncertainty_threshold)
        self.running_vote: np.ndarray | None = None
        self.beeps_count: int = 0
        self.classes: list[str] = list(CLASSES_DEFAULT)
        self.scaler: Any | None = None
        self.model: Any | None = None
        self.bundle: dict[str, Any] = {}

        # Resolve model path
        resolved_path = None
        if model_path is not None:
            resolved_path = Path(model_path)
        else:
            candidates = [
                DEFAULT_MODEL_PATH,
                Path(__file__).resolve().parent.parent / "artifacts" / "location_model.joblib",
                Path(__file__).resolve().parent / "artifacts" / "location_model.joblib",
            ]
            for candidate in candidates:
                if candidate.exists():
                    resolved_path = candidate
                    break

        if resolved_path is not None and resolved_path.exists():
            self.load(resolved_path)

    def reset(self) -> None:
        """Reset running vote across consecutive beeps."""
        self.running_vote = None
        self.beeps_count = 0

    def load(self, model_path: Path | str) -> None:
        """Load trained model bundle from joblib file."""
        path = Path(model_path)
        if not path.exists():
            raise FileNotFoundError(f"Model file not found at: {path}")

        loaded = joblib.load(path)
        if isinstance(loaded, dict) and "model" in loaded:
            self.bundle = loaded
            self.model = loaded["model"]
            self.scaler = loaded.get("scaler")
            if "classes" in loaded:
                self.classes = list(loaded["classes"])
            elif hasattr(self.model, "classes_"):
                self.classes = list(self.model.classes_)
        else:
            self.bundle = {"model": loaded}
            self.model = loaded
            self.scaler = None
            if hasattr(self.model, "classes_"):
                self.classes = list(self.model.classes_)
            else:
                self.classes = list(CLASSES_DEFAULT)

    def update_running_vote(
        self,
        probabilities: dict[str, float] | np.ndarray | list[float],
    ) -> dict[str, Any]:
        """Update running vote using exponential smoothing across multiple consecutive beeps.

        Parameters
        ----------
        probabilities : dict[str, float] | np.ndarray | list[float]
            Single-beep class probabilities. Either a dictionary mapping class names
            to probabilities, or an array-like matching self.classes order.

        Returns
        -------
        dict[str, Any]
            Decision dictionary containing:
              - 'rack': predicted rack name
              - 'confidence': max probability
              - 'uncertain': bool (True if max probability < 0.60)
              - 'probabilities': dict of smoothed class probabilities
              - 'runner_up': dict with second-choice rack and probability
              - 'beeps': number of consecutive beeps integrated
        """
        # Convert input into aligned numpy array
        if isinstance(probabilities, dict):
            p = np.array(
                [float(probabilities.get(cls, 0.0)) for cls in self.classes],
                dtype=np.float64,
            )
        else:
            p = np.asarray(probabilities, dtype=np.float64).flatten()
            if len(p) != len(self.classes):
                raise ValueError(
                    f"Probability vector length {len(p)} does not match classes {self.classes}"
                )

        # Normalize incoming probability vector
        sum_p = float(np.sum(p))
        if sum_p > 1e-9:
            p = p / sum_p
        else:
            p = np.full(len(self.classes), 1.0 / len(self.classes), dtype=np.float64)

        # Apply exponential smoothing: V_t = alpha * P_t + (1 - alpha) * V_{t-1}
        if self.running_vote is None:
            self.running_vote = p.copy()
        else:
            self.running_vote = self.alpha * p + (1.0 - self.alpha) * self.running_vote

        self.beeps_count += 1

        # Re-normalize running vote
        vote_sum = float(np.sum(self.running_vote))
        if vote_sum > 1e-9:
            vote = self.running_vote / vote_sum
        else:
            vote = np.full(len(self.classes), 1.0 / len(self.classes), dtype=np.float64)
        self.running_vote = vote

        # Find top prediction and runner up
        order = np.argsort(vote)[::-1]
        top_idx = int(order[0])
        max_p = float(vote[top_idx])
        top_class = self.classes[top_idx]

        runner_up_idx = int(order[1]) if len(order) > 1 else top_idx
        runner_up_class = self.classes[runner_up_idx]
        runner_up_p = float(vote[runner_up_idx])

        # Check uncertainty threshold (< 0.60)
        uncertain = bool(max_p < self.uncertainty_threshold)

        prob_dict = {
            cls: float(round(vote[i], 4)) for i, cls in enumerate(self.classes)
        }

        result = {
            "rack": top_class,
            "confidence": float(round(max_p, 4)),
            "uncertain": uncertain,
            "probabilities": prob_dict,
            "runner_up": {
                "rack": runner_up_class,
                "p": float(round(runner_up_p, 4)),
            },
            "beeps": self.beeps_count,
        }

        return result

    def predict_proba(self, features: np.ndarray) -> dict[str, float]:
        """Compute raw class probabilities for a single beep's 19 features.

        Parameters
        ----------
        features : np.ndarray
            19-element spatial features array.

        Returns
        -------
        dict[str, float]
            Mapping of class name to probability.
        """
        if self.model is None:
            raise RuntimeError("No model is loaded. Call load() or provide model_path.")

        feat = np.asarray(features, dtype=np.float64).reshape(1, -1)
        if self.scaler is not None:
            feat = self.scaler.transform(feat)

        probs = self.model.predict_proba(feat)[0]
        return {cls: float(round(probs[i], 4)) for i, cls in enumerate(self.classes)}

    def predict(
        self,
        features: np.ndarray,
        update_vote: bool = True,
    ) -> dict[str, Any]:
        """Classify location for a single beep and update running vote.

        Parameters
        ----------
        features : np.ndarray
            19-element spatial features array.
        update_vote : bool, optional
            Whether to update running vote across beeps (default: True).

        Returns
        -------
        dict[str, Any]
            Prediction decision dictionary.
        """
        raw_probs = self.predict_proba(features)
        if update_vote:
            return self.update_running_vote(raw_probs)

        # Single-shot prediction without updating running vote
        top_cls = max(raw_probs, key=raw_probs.get)
        max_p = raw_probs[top_cls]
        sorted_probs = sorted(raw_probs.items(), key=lambda kv: kv[1], reverse=True)
        runner_up = sorted_probs[1] if len(sorted_probs) > 1 else sorted_probs[0]

        return {
            "rack": top_cls,
            "confidence": max_p,
            "uncertain": bool(max_p < self.uncertainty_threshold),
            "probabilities": raw_probs,
            "runner_up": {"rack": runner_up[0], "p": runner_up[1]},
            "beeps": 1,
        }

    def reset_running_vote(self) -> None:
        """Reset running vote smoothing state for a new incident or session."""
        self.running_vote = None
        self.beeps_count = 0

