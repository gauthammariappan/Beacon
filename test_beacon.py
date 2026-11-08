"""Comprehensive unit tests for Beacon v2.1 signal processing and spatial features."""

import unittest
import numpy as np

from beacon.signal import SignalProcessor, compute_purity
from beacon.features import extract_spatial_features


class TestBeaconSignalAndFeatures(unittest.TestCase):
    def test_compute_purity(self):
        # Symmetric sidebands
        e25 = np.array([100.0, 50.0, 10.0])
        e20 = np.array([10.0, 10.0, 10.0])
        e30 = np.array([10.0, 10.0, 10.0])
        p = compute_purity(e25, e20, e30)
        self.assertTrue(np.allclose(p, [10.0, 5.0, 1.0]))

        # Zero sidebands safeguard
        p_zero = compute_purity([50.0, 0.0], [0.0, 0.0], [0.0, 0.0])
        self.assertGreater(p_zero[0], 1e6)
        self.assertEqual(p_zero[1], 0.0)

    def test_extract_spatial_features_structure_and_values(self):
        # Construct 3 active frames at 50 Hz (20 ms interval: 100, 120, 140 ms)
        # L25: [100, 200, 300] -> avg = 200, max = 300
        # M25: [50, 100, 150]  -> avg = 100, max = 150
        # R25: [25, 50, 75]    -> avg = 50,  max = 75
        # Total avg = 350
        # Sidebands: e20 = 10, e30 = 10 -> avg = 10 -> purity = e25 / 10
        # L purity: [10, 20, 30] -> avg = 20
        # M purity: [5, 10, 15]  -> avg = 10
        # R purity: [2.5, 5, 7.5] -> avg = 5
        active_frames = [
            {
                "ms": 100.0,
                "L25": 100.0, "M25": 50.0, "R25": 25.0,
                "L20": 10.0, "M20": 10.0, "R20": 10.0,
                "L30": 10.0, "M30": 10.0, "R30": 10.0,
            },
            {
                "ms": 120.0,
                "L25": 200.0, "M25": 100.0, "R25": 50.0,
                "L20": 10.0, "M20": 10.0, "R20": 10.0,
                "L30": 10.0, "M30": 10.0, "R30": 10.0,
            },
            {
                "ms": 140.0,
                "L25": 300.0, "M25": 150.0, "R25": 75.0,
                "L20": 10.0, "M20": 10.0, "R20": 10.0,
                "L30": 10.0, "M30": 10.0, "R30": 10.0,
            },
        ]

        noise_floor = np.array([20.0, 10.0, 5.0])
        features = extract_spatial_features(active_frames, noise_floor)

        self.assertIsInstance(features, np.ndarray)
        self.assertEqual(features.shape, (19,))
        self.assertEqual(features.dtype, np.float64)

        # 1. 3 average 2500Hz energies (raw)
        self.assertTrue(np.allclose(features[0:3], [200.0, 100.0, 50.0]))

        # 2. 3 normalized shares (normalized_energy = [200/20, 100/10, 50/5] = [10, 10, 10])
        self.assertTrue(np.allclose(features[3:6], [1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0]))
        self.assertTrue(np.isclose(np.sum(features[3:6]), 1.0))

        # 3. 3 normalized log ratios: log(10/10)=0, log(10/10)=0, log(10/10)=0
        self.assertTrue(np.isclose(features[6], 0.0))
        self.assertTrue(np.isclose(features[7], 0.0))
        self.assertTrue(np.isclose(features[8], 0.0))

        # Also verify symmetric noise floor retains unskewed spatial shares and log-ratios
        features_eq = extract_spatial_features(active_frames, np.array([10.0, 10.0, 10.0]))
        self.assertTrue(np.allclose(features_eq[3:6], [200.0 / 350.0, 100.0 / 350.0, 50.0 / 350.0]))
        self.assertTrue(np.isclose(features_eq[6], np.log(200.0 / 100.0)))
        self.assertTrue(np.isclose(features_eq[7], np.log(100.0 / 50.0)))
        self.assertTrue(np.isclose(features_eq[8], np.log(200.0 / 50.0)))

        # 4. 3 peak energies
        self.assertTrue(np.allclose(features[9:12], [300.0, 150.0, 75.0]))

        # 5. 3 SNRs in dB: 10 * log10(avg / noise_floor)
        self.assertTrue(np.allclose(features[12:15], [10.0, 10.0, 10.0]))

        # 6. 3 average purities
        self.assertTrue(np.allclose(features[15:18], [20.0, 10.0, 5.0]))

        # 7. 1 duration in ms: 140 - 100 = 40 ms
        self.assertTrue(np.isclose(features[18], 40.0))

    def test_extract_spatial_features_empty(self):
        features = extract_spatial_features([], np.array([10.0, 10.0, 10.0]))
        self.assertIsInstance(features, np.ndarray)
        self.assertEqual(features.shape, (19,))
        self.assertTrue(np.all(features == 0.0))

    def test_signal_processor_noise_floor_ewma(self):
        sp = SignalProcessor(alpha=0.02, initial_noise_floor=[10.0, 10.0, 10.0])
        self.assertTrue(np.allclose(sp.noise_floor, [10.0, 10.0, 10.0]))

        # Frame below threshold: L25=12, M25=12, R25=12, low purity
        line = "E,100,12,12,12,12,12,12,12,12,12"
        sp.process_line(line)
        self.assertFalse(sp.is_beep_active)
        self.assertTrue(np.allclose(sp.noise_floor, [10.04, 10.04, 10.04]))

    def test_schmitt_trigger_detection_and_freezing(self):
        sp = SignalProcessor(alpha=0.02, initial_noise_floor=[10.0, 10.0, 10.0])

        # Frame 1: quiet frame
        sp.process_line("E,1000,10,10,10,10,10,10,10,10,10")
        nf_before_beep = sp.noise_floor.copy()
        self.assertFalse(sp.is_beep_active)

        # Frame 2: Mic M is > 5x its noise floor (60 > 50) and purity = 12 > 2.5
        sp.process_line("E,1020,10,60,10,5,5,5,5,5,5")
        self.assertTrue(sp.is_beep_active)
        # Noise floor must freeze!
        self.assertTrue(np.allclose(sp.noise_floor, nf_before_beep))

        # Frame 3: Active beep continues
        sp.process_line("E,1040,10,70,10,5,5,5,5,5,5")
        self.assertTrue(sp.is_beep_active)
        self.assertTrue(np.allclose(sp.noise_floor, nf_before_beep))

        # Frame 4: Drop below 2x noise floor (< 20) for 1 frame
        event = sp.process_line("E,1060,15,15,15,5,5,5,5,5,5")
        self.assertTrue(sp.is_beep_active)
        self.assertIsNone(event)
        self.assertEqual(sp.consecutive_quiet, 1)
        self.assertTrue(np.allclose(sp.noise_floor, nf_before_beep))

        # Frame 5: Second consecutive frame < 2x noise floor -> Beep ENDs
        event = sp.process_line("E,1080,15,15,15,5,5,5,5,5,5")
        self.assertFalse(sp.is_beep_active)
        self.assertIsNotNone(event)
        self.assertEqual(len(event.features), 19)
        self.assertEqual(len(event.frames), 2)
        self.assertEqual(event.frames[0]["ms"], 1020.0)
        self.assertEqual(event.frames[1]["ms"], 1040.0)

        # Frame 6: Noise floor should resume updating
        sp.process_line("E,1100,10,10,10,10,10,10,10,10,10")
        self.assertFalse(sp.is_beep_active)

    def test_trigger_blanking(self):
        sp = SignalProcessor(alpha=0.02, initial_noise_floor=[10.0, 10.0, 10.0])
        sp.process_line("E,1000,10,10,10,10,10,10,10,10,10")
        self.assertEqual(sp.last_ms, 1000.0)

        # Trigger servo blanking for 350 ms (from 1000 to 1350 ms)
        sp.trigger_blanking(350.0)
        self.assertEqual(sp.blank_until_ms, 1350.0)

        # Loud frame during servo movement at 1100 ms should be IGNORED
        res = sp.process_line("E,1100,100,100,100,2,2,2,2,2,2")
        self.assertIsNone(res)
        self.assertFalse(sp.is_beep_active)
        self.assertTrue(np.allclose(sp.noise_floor, [10.0, 10.0, 10.0]))

        # Another frame during blanking at 1340 ms
        sp.process_line("E,1340,100,100,100,2,2,2,2,2,2")
        self.assertFalse(sp.is_beep_active)

        # Frame after blanking at 1360 ms (>= 1350) should be PROCESSED
        sp.process_line("E,1360,100,100,100,2,2,2,2,2,2")
        self.assertTrue(sp.is_beep_active)

    def test_process_frame_blanking_with_t_ms(self):
        sp = SignalProcessor(alpha=0.02, initial_noise_floor=[10.0, 10.0, 10.0])
        # Initial quiet frame establishes last_ms = 2000.0
        frame0 = {
            "t_ms": 2000.0,
            "L25": 10.0, "M25": 10.0, "R25": 10.0,
            "L20": 10.0, "M20": 10.0, "R20": 10.0,
            "L30": 10.0, "M30": 10.0, "R30": 10.0,
        }
        sp.process_frame(frame0)
        self.assertEqual(sp.last_ms, 2000.0)

        # Trigger acoustic blanking for 350 ms -> blank until 2350.0 ms
        sp.trigger_blanking(350)
        self.assertEqual(sp.blank_until_ms, 2350.0)

        # Loud frame within blanking interval (t_ms = 2200 < 2350) MUST be dropped
        loud_frame = {
            "t_ms": 2200.0,
            "L25": 200.0, "M25": 200.0, "R25": 200.0,
            "L20": 2.0, "M20": 2.0, "R20": 2.0,
            "L30": 2.0, "M30": 2.0, "R30": 2.0,
        }
        res = sp.process_frame(loud_frame)
        self.assertIsNone(res)
        self.assertFalse(sp.is_beep_active)
        self.assertTrue(np.allclose(sp.noise_floor, [10.0, 10.0, 10.0]))

        # Another loud frame still within blanking interval (t_ms = 2340 < 2350)
        loud_frame_2 = dict(loud_frame, t_ms=2340.0)
        res2 = sp.process_frame(loud_frame_2)
        self.assertIsNone(res2)
        self.assertFalse(sp.is_beep_active)

        # Loud frame past blanking interval (t_ms = 2360 >= 2350) is processed normally
        post_blank_frame = dict(loud_frame, t_ms=2360.0)
        sp.process_frame(post_blank_frame)
        self.assertTrue(sp.is_beep_active)

    def test_schmitt_trigger_no_false_alarm_on_broadband_noise(self):
        sp = SignalProcessor(alpha=0.02, initial_noise_floor=[10.0, 10.0, 10.0])
        # L25=60, L20=60, L30=60 -> purity = 1.0 (<= 2.5)
        sp.process_line("E,1000,60,60,60,60,60,60,60,60,60")
        self.assertFalse(sp.is_beep_active)

    def test_schmitt_trigger_quiet_interruption_resets_counter(self):
        sp = SignalProcessor(alpha=0.02, initial_noise_floor=[10.0, 10.0, 10.0])
        sp.process_line("E,1000,60,60,60,5,5,5,5,5,5")
        self.assertTrue(sp.is_beep_active)

        sp.process_line("E,1020,10,10,10,5,5,5,5,5,5")
        self.assertEqual(sp.consecutive_quiet, 1)
        self.assertTrue(sp.is_beep_active)

        # Loud frame resets quiet counter
        sp.process_line("E,1040,60,60,60,5,5,5,5,5,5")
        self.assertEqual(sp.consecutive_quiet, 0)
        self.assertTrue(sp.is_beep_active)

    def test_beep_event_contract(self):
        sp = SignalProcessor(alpha=0.02, initial_noise_floor=[10.0, 10.0, 10.0])
        sp.process_line("E,12100,60,10,10,5,5,5,5,5,5")
        sp.process_line("E,12200,60,10,10,5,5,5,5,5,5")
        sp.process_line("E,12300,60,10,10,5,5,5,5,5,5")
        sp.process_line("E,12320,10,10,10,5,5,5,5,5,5")
        event = sp.process_line("E,12340,10,10,10,5,5,5,5,5,5")

        self.assertIsNotNone(event)
        contract = event.to_contract_dict()
        self.assertIn("id", contract)
        self.assertEqual(contract["t_start"], 12.1)
        self.assertEqual(contract["t_end"], 12.3)
        self.assertEqual(contract["features"]["dur_ms"], 200.0)
        self.assertEqual(len(contract["features"]["share"]), 3)
        self.assertEqual(len(contract["features"]["log_ratio"]), 3)
        self.assertEqual(len(contract["features"]["peak"]), 3)
        self.assertEqual(len(contract["features"]["snr_db"]), 3)
        self.assertEqual(len(contract["features"]["purity"]), 3)


if __name__ == "__main__":
    unittest.main()
