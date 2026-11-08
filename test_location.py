"""Unit tests for Beacon v2.1 location classifier and training tool."""

import json
from pathlib import Path
import unittest
import numpy as np

from beacon.location_model import LocationClassifier
from tools.train_location import (
    CLASSES,
    predict_loudest_mic,
    predict_weighted_centroid,
)


class TestLocationModel(unittest.TestCase):
    def setUp(self):
        self.model_path = Path("artifacts/location_model.joblib")
        self.metrics_path = Path("artifacts/location_metrics.json")

    def test_artifacts_exist_and_valid(self):
        self.assertTrue(self.model_path.exists(), "location_model.joblib should exist")
        self.assertTrue(self.metrics_path.exists(), "location_metrics.json should exist")

        with open(self.metrics_path, encoding="utf-8") as f:
            metrics = json.load(f)

        self.assertIn("loudest_mic", metrics)
        self.assertIn("weighted_centroid", metrics)
        self.assertIn("random_forest", metrics)
        self.assertIn("winning_model", metrics)

        # Check accuracies exist and are numbers
        self.assertIsInstance(metrics["loudest_mic"]["accuracy"], float)
        self.assertIsInstance(metrics["weighted_centroid"]["accuracy"], float)
        self.assertIsInstance(metrics["random_forest"]["accuracy"], float)

        # Check confusion matrices have shape (6, 6)
        for method in ["loudest_mic", "weighted_centroid", "random_forest"]:
            cm = metrics[method]["confusion_matrix"]
            self.assertEqual(len(cm), 6)
            for row in cm:
                self.assertEqual(len(row), 6)

    def test_baselines_logic(self):
        # Synthetic feature matrix (3 samples)
        # Sample 0: L is loudest (100, 20, 10), shares: (0.77, 0.15, 0.08) -> A
        # Sample 1: M is loudest (20, 100, 20), shares: (0.14, 0.72, 0.14) -> C
        # Sample 2: R is loudest (10, 20, 100), shares: (0.08, 0.15, 0.77) -> E
        # Sample 3: L and M equal (50, 50, 10), shares: (0.45, 0.45, 0.10) -> centroid B
        # Sample 4: M and R equal (10, 50, 50), shares: (0.10, 0.45, 0.45) -> centroid D
        X = np.zeros((5, 19), dtype=np.float64)

        # Sample 0: pure A
        X[0, 0:3] = [150.0, 15.0, 5.0]
        X[0, 3:6] = [0.88, 0.09, 0.03]

        # Sample 1: pure C
        X[1, 0:3] = [15.0, 150.0, 15.0]
        X[1, 3:6] = [0.08, 0.84, 0.08]

        # Sample 2: pure E
        X[2, 0:3] = [5.0, 15.0, 150.0]
        X[2, 3:6] = [0.03, 0.09, 0.88]

        # Sample 3: Rack B
        X[3, 0:3] = [50.0, 50.0, 10.0]
        X[3, 3:6] = [0.45, 0.45, 0.10]

        # Sample 4: Rack D
        X[4, 0:3] = [10.0, 50.0, 50.0]
        X[4, 3:6] = [0.10, 0.45, 0.45]

        # Loudest mic test
        pred_loudest = predict_loudest_mic(X)
        self.assertEqual(pred_loudest[0], "A")
        self.assertEqual(pred_loudest[1], "C")
        self.assertEqual(pred_loudest[2], "E")
        # Loudest mic can only predict A, C, or E - never B or D
        self.assertIn(pred_loudest[3], ["A", "C"])
        self.assertIn(pred_loudest[4], ["C", "E"])

        # Weighted centroid test
        pred_centroid = predict_weighted_centroid(X)
        self.assertEqual(pred_centroid[0], "A")
        self.assertEqual(pred_centroid[1], "C")
        self.assertEqual(pred_centroid[2], "E")
        self.assertEqual(pred_centroid[3], "B")  # Centroid successfully names B!
        self.assertEqual(pred_centroid[4], "D")  # Centroid successfully names D!

    def test_location_classifier_running_vote_and_uncertainty(self):
        clf = LocationClassifier(self.model_path, alpha=0.3, uncertainty_threshold=0.60)
        self.assertEqual(clf.classes, CLASSES)

        # 1. Single uncertain beep (< 0.60)
        probs_uncertain = {"A": 0.45, "B": 0.35, "C": 0.10, "D": 0.05, "E": 0.03, "NONE": 0.02}
        vote1 = clf.update_running_vote(probs_uncertain)
        self.assertEqual(vote1["rack"], "A")
        self.assertTrue(vote1["uncertain"], "Should be uncertain when max prob < 0.60")
        self.assertAlmostEqual(vote1["confidence"], 0.45, places=2)
        self.assertEqual(vote1["runner_up"]["rack"], "B")
        self.assertEqual(vote1["beeps"], 1)

        # 2. Second beep favoring A
        probs_confident = {"A": 0.90, "B": 0.05, "C": 0.02, "D": 0.01, "E": 0.01, "NONE": 0.01}
        vote2 = clf.update_running_vote(probs_confident)
        # Smoothing: 0.3 * 0.90 + 0.7 * 0.45 = 0.27 + 0.315 = 0.585 (< 0.60)
        self.assertEqual(vote2["rack"], "A")
        self.assertTrue(vote2["uncertain"])
        self.assertEqual(vote2["beeps"], 2)

        # 3. Third beep favoring A confirms prediction
        vote3 = clf.update_running_vote(probs_confident)
        # Smoothing: 0.3 * 0.90 + 0.7 * 0.585 = 0.27 + 0.4095 = 0.6795 (>= 0.60)
        self.assertEqual(vote3["rack"], "A")
        self.assertFalse(vote3["uncertain"], "Should become confident (>= 0.60)")
        self.assertGreaterEqual(vote3["confidence"], 0.60)
        self.assertEqual(vote3["beeps"], 3)

        # Reset running vote
        clf.reset_running_vote()
        self.assertIsNone(clf.running_vote)
        self.assertEqual(clf.beeps_count, 0)

    def test_location_classifier_predict_proba_and_predict(self):
        clf = LocationClassifier(self.model_path)
        # Synthetic feature vector
        sample_features = np.array([
            200.0, 40.0, 10.0,      # avg energies (A rack loud on L)
            0.80, 0.16, 0.04,       # shares
            1.6, 1.4, 3.0,          # log ratios
            220.0, 50.0, 12.0,      # peaks
            13.0, 6.0, 0.0,         # SNRs
            12.0, 8.0, 5.0,         # purities
            140.0                   # duration
        ], dtype=np.float64)

        raw_probs = clf.predict_proba(sample_features)
        self.assertIsInstance(raw_probs, dict)
        self.assertEqual(len(raw_probs), 6)
        self.assertIn("A", raw_probs)
        self.assertAlmostEqual(sum(raw_probs.values()), 1.0, places=2)

        clf.reset_running_vote()
        decision = clf.predict(sample_features, update_vote=True)
        self.assertIn("rack", decision)
        self.assertIn("confidence", decision)
        self.assertIn("uncertain", decision)
        self.assertEqual(decision["rack"], "A")

    def test_real_recordings_dataset_segmentation(self):
        from tools.train_location import load_dataset_from_csv
        from beacon.signal import SignalProcessor
        from collections import Counter

        train_path = Path("recordings/session1_train.csv")
        test_path = Path("recordings/session2_test.csv")
        if train_path.exists() and test_path.exists():
            sp_train = SignalProcessor(alpha=0.02, initial_noise_floor=[10.0, 10.0, 10.0])
            X_tr, y_tr = load_dataset_from_csv(train_path, processor=sp_train)
            self.assertEqual(len(y_tr), 240)
            train_counts = Counter(y_tr)
            for cls in CLASSES:
                self.assertEqual(train_counts[cls], 40)

            sp_test = SignalProcessor(alpha=0.02, initial_noise_floor=[10.0, 10.0, 10.0])
            X_te, y_te = load_dataset_from_csv(test_path, processor=sp_test)
            self.assertEqual(len(y_te), 150)
            test_counts = Counter(y_te)
            for cls in CLASSES:
                self.assertEqual(test_counts[cls], 25)


if __name__ == "__main__":
    unittest.main()
