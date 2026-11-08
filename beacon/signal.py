"""Signal processing and beep detection for Beacon v2.1 acoustic localization."""

from __future__ import annotations

import math
from typing import Any
import numpy as np

try:
    from .features import extract_spatial_features
except ImportError:
    try:
        from beacon.features import extract_spatial_features
    except ImportError:
        from features import extract_spatial_features


def compute_purity(
    e2500: np.ndarray | list[float] | float,
    e2000: np.ndarray | list[float] | float,
    e3000: np.ndarray | list[float] | float,
    eps: float = 1e-9,
) -> np.ndarray:
    """Compute purity: e2500 / avg(e2000, e3000).

    Parameters
    ----------
    e2500 : array-like or float
        Energy at 2500 Hz for microphones [Left, Middle, Right].
    e2000 : array-like or float
        Energy at 2000 Hz for microphones [Left, Middle, Right].
    e3000 : array-like or float
        Energy at 3000 Hz for microphones [Left, Middle, Right].
    eps : float, optional
        Safeguard against division by zero, by default 1e-9.

    Returns
    -------
    np.ndarray
        Purity ratio for each microphone.
    """
    e25 = np.asarray(e2500, dtype=np.float64)
    e20 = np.asarray(e2000, dtype=np.float64)
    e30 = np.asarray(e3000, dtype=np.float64)

    avg_side = 0.5 * (e20 + e30)
    safe_side = np.maximum(avg_side, eps)
    purity = np.where(e25 == 0.0, 0.0, e25 / safe_side)
    return purity


class BeepEvent(dict):
    """Event returned when an active beep finishes detection.

    Inherits from dict so it can be indexed by key (e.g. event['features']),
    while also behaving like a list of frames when indexed by integer or iterated over.
    """

    def __init__(
        self,
        frames: list[dict[str, Any]],
        noise_floor: np.ndarray,
        features: np.ndarray | None = None,
        raw_frames: list[dict[str, Any]] | None = None,
        event_id: str | None = None,
    ):
        super().__init__()
        self["id"] = event_id or ""
        self["frames"] = frames
        self["noise_floor"] = noise_floor
        self["features"] = features
        self["raw_frames"] = raw_frames if raw_frames is not None else frames

        if frames:
            t0 = float(frames[0].get("ms", frames[0].get("timestamp", 0.0)))
            t1 = float(frames[-1].get("ms", frames[-1].get("timestamp", 0.0)))
            self["start_ms"] = t0
            self["end_ms"] = t1
            self["duration_ms"] = t1 - t0
            self["t_start"] = round(t0 / 1000.0, 3)
            self["t_end"] = round(t1 / 1000.0, 3)
        else:
            self["start_ms"] = 0.0
            self["end_ms"] = 0.0
            self["duration_ms"] = 0.0
            self["t_start"] = 0.0
            self["t_end"] = 0.0

        if features is not None and len(features) == 19:
            self["features_dict"] = {
                "avg_2500": features[0:3].tolist(),
                "share": features[3:6].tolist(),
                "log_ratio": features[6:9].tolist(),
                "peak": features[9:12].tolist(),
                "snr_db": features[12:15].tolist(),
                "purity": features[15:18].tolist(),
                "dur_ms": float(features[18]),
            }
        else:
            self["features_dict"] = {}

    @property
    def frames(self) -> list[dict[str, Any]]:
        return self["frames"]

    @property
    def raw_frames(self) -> list[dict[str, Any]]:
        return self["raw_frames"]

    @property
    def noise_floor(self) -> np.ndarray:
        return self["noise_floor"]

    @property
    def features(self) -> np.ndarray | None:
        return self["features"]

    def to_contract_dict(self, event_id: str | None = None) -> dict[str, Any]:
        """Format event to match Beacon architecture layer 3 -> 4 data contract."""
        eid = event_id or self.get("id") or "ev"
        feat_dict = self.get("features_dict", {})
        return {
            "id": eid,
            "t_start": self.get("t_start", 0.0),
            "t_end": self.get("t_end", 0.0),
            "features": {
                "share": feat_dict.get("share", []),
                "log_ratio": feat_dict.get("log_ratio", []),
                "peak": feat_dict.get("peak", []),
                "snr_db": feat_dict.get("snr_db", []),
                "purity": feat_dict.get("purity", []),
                "dur_ms": feat_dict.get("dur_ms", self.get("duration_ms", 0.0)),
            },
        }

    def __iter__(self):
        return iter(self["frames"])

    def __len__(self) -> int:
        return len(self["frames"])

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return self["frames"][key]
        return super().__getitem__(key)


class SignalProcessor:
    """Processes 50 Hz serial lines from Beacon v2.1 hardware microphones.

    Attributes
    ----------
    alpha : float
        Smoothing factor for EWMA noise floor estimation (default: 0.02).
    noise_floor : np.ndarray | None
        Running noise floor array of shape (3,) for [Left, Middle, Right] mics.
        Freezes when a beep is active.
    is_beep_active : bool
        True when a beep is currently active.
    active_frames : list[dict]
        Active frames collected during the current or most recent beep.
    completed_beeps : list[BeepEvent]
        History of completed beep events.
    """

    def __init__(
        self,
        alpha: float = 0.02,
        initial_noise_floor: np.ndarray | list[float] | float | None = None,
    ) -> None:
        self.alpha: float = float(alpha)
        if initial_noise_floor is not None:
            nf = np.asarray(initial_noise_floor, dtype=np.float64)
            if nf.ndim == 0:
                self.noise_floor: np.ndarray | None = np.full(3, float(nf), dtype=np.float64)
            elif nf.shape == (3,):
                self.noise_floor = nf.copy()
            else:
                self.noise_floor = np.resize(nf, 3).astype(np.float64)
        else:
            self.noise_floor = None

        self.is_beep_active: bool = False
        self._consecutive_quiet: int = 0
        self.active_frames: list[dict[str, Any]] = []
        self._current_run_frames: list[dict[str, Any]] = []

        self.blank_until_ms: float | None = None
        self._blank_pending_ms: float | None = None
        self._blank_frames_remaining: int = 0
        self.last_ms: float | None = None

        self.last_beep: BeepEvent | None = None
        self.completed_beeps: list[BeepEvent] = []
        self._event_counter: int = 0

    @property
    def beep_active(self) -> bool:
        """Alias for is_beep_active."""
        return self.is_beep_active

    @property
    def consecutive_quiet(self) -> int:
        """Number of consecutive frames meeting the quiet threshold."""
        return self._consecutive_quiet

    def trigger_blanking(self, duration_ms: float = 350.0) -> None:
        """Trigger blanking to ignore frames after servo movement.

        Parameters
        ----------
        duration_ms : float, optional
            Duration in milliseconds to blank incoming frames (default: 350 ms).
        """
        duration = float(duration_ms)
        if self.last_ms is not None:
            self.blank_until_ms = self.last_ms + duration
            self._blank_pending_ms = None
        else:
            # If no frame timestamp has been seen yet, arm blanking on the first frame
            self._blank_pending_ms = duration
            self.blank_until_ms = None

        # Also arm frame counter (50 Hz = 20 ms / frame) for timestamp-free fallback
        self._blank_frames_remaining = int(math.ceil(duration / 20.0))

        # Servo movement invalidates any in-progress beep detection
        if self.is_beep_active:
            self.is_beep_active = False
            self._consecutive_quiet = 0
            self._current_run_frames.clear()

    @staticmethod
    def compute_purity(
        e2500: np.ndarray | list[float] | float,
        e2000: np.ndarray | list[float] | float,
        e3000: np.ndarray | list[float] | float,
    ) -> np.ndarray:
        """Compute purity: e2500 / avg(e2000, e3000)."""
        return compute_purity(e2500, e2000, e3000)

    def parse_line(self, line: str) -> dict[str, Any] | None:
        """Parse a 50 Hz serial line into a structured frame dictionary.

        Format: E,<ms>,L25,M25,R25,L20,M20,R20,L30,M30,R30
        """
        raw = line.strip()
        if not raw:
            return None

        tokens = [t.strip() for t in raw.split(",")]
        if not tokens or tokens[0].upper() != "E":
            return None

        if len(tokens) < 11:
            return None

        try:
            ms = float(tokens[1])
            l25, m25, r25 = float(tokens[2]), float(tokens[3]), float(tokens[4])
            l20, m20, r20 = float(tokens[5]), float(tokens[6]), float(tokens[7])
            l30, m30, r30 = float(tokens[8]), float(tokens[9]), float(tokens[10])
        except (ValueError, TypeError):
            return None

        e2500 = np.array([l25, m25, r25], dtype=np.float64)
        e2000 = np.array([l20, m20, r20], dtype=np.float64)
        e3000 = np.array([l30, m30, r30], dtype=np.float64)
        purity = compute_purity(e2500, e2000, e3000)

        frame: dict[str, Any] = {
            "ms": ms,
            "timestamp": ms,
            "L25": l25,
            "M25": m25,
            "R25": r25,
            "L20": l20,
            "M20": m20,
            "R20": r20,
            "L30": l30,
            "M30": m30,
            "R30": r30,
            "e2500": e2500,
            "e2000": e2000,
            "e3000": e3000,
            "purity": purity,
        }
        return frame

    def process_line(self, line: str) -> BeepEvent | None:
        """Parse and process one 50 Hz serial line.

        Parameters
        ----------
        line : str
            Serial line matching 'E,<ms>,L25,M25,R25,L20,M20,R20,L30,M30,R30'.

        Returns
        -------
        BeepEvent | None
            A completed BeepEvent when a beep ends; None otherwise.
        """
        frame = self.parse_line(line)
        if frame is None:
            return None
        return self.process_frame(frame)

    def process_frame(self, frame: dict[str, Any]) -> BeepEvent | None:
        """Process one acoustic energy frame dictionary.

        Evaluates blanking, Schmitt trigger start/end, EWMA noise floor update,
        and returns a BeepEvent when an active beep ends.

        Parameters
        ----------
        frame : dict
            Dictionary containing energy values and timestamp.

        Returns
        -------
        BeepEvent | None
            A completed BeepEvent when a beep ends; None otherwise.
        """
        # 1. Timestamp and Blanking evaluation
        ms = frame.get("ms", frame.get("timestamp", None))

        if ms is not None:
            ms = float(ms)
            # Arm pending blanking if trigger_blanking was called before any timestamp
            if self._blank_pending_ms is not None:
                self.blank_until_ms = ms + self._blank_pending_ms
                self._blank_pending_ms = None

            is_blanked = False
            if self.blank_until_ms is not None:
                if ms < self.blank_until_ms:
                    is_blanked = True
                else:
                    self.blank_until_ms = None

            self.last_ms = ms
            if is_blanked:
                return None
        else:
            # Fallback when frames have no timestamps
            if self._blank_frames_remaining > 0:
                self._blank_frames_remaining -= 1
                return None

        # 2. Extract energies and ensure purity is computed
        if "e2500" in frame:
            e2500 = np.asarray(frame["e2500"], dtype=np.float64)
        else:
            e2500 = np.array([frame["L25"], frame["M25"], frame["R25"]], dtype=np.float64)
            frame["e2500"] = e2500

        if "e2000" in frame and "e3000" in frame:
            e2000 = np.asarray(frame["e2000"], dtype=np.float64)
            e3000 = np.asarray(frame["e3000"], dtype=np.float64)
        elif "L20" in frame and "L30" in frame:
            e2000 = np.array([frame["L20"], frame["M20"], frame["R20"]], dtype=np.float64)
            e3000 = np.array([frame["L30"], frame["M30"], frame["R30"]], dtype=np.float64)
            frame["e2000"] = e2000
            frame["e3000"] = e3000
        else:
            e2000 = np.zeros(3, dtype=np.float64)
            e3000 = np.zeros(3, dtype=np.float64)

        if "purity" in frame:
            purity = np.asarray(frame["purity"], dtype=np.float64)
        else:
            purity = compute_purity(e2500, e2000, e3000)
            frame["purity"] = purity

        # 3. Initialize noise floor if not already established
        if self.noise_floor is None:
            self.noise_floor = e2500.copy()
            return None

        # 4. Schmitt trigger logic
        if not self.is_beep_active:
            # START condition: any mic is > 5x its noise floor with purity > 2.5
            start_condition = (e2500 > 5.0 * self.noise_floor) & (purity > 2.5)

            if bool(np.any(start_condition)):
                self.is_beep_active = True
                self._consecutive_quiet = 0
                self._current_run_frames = [frame]
                self.active_frames = self._current_run_frames
                # Noise floor freezes while beep is active
                return None
            else:
                # Update running noise floor using EWMA (alpha = 0.02)
                self.noise_floor = (1.0 - self.alpha) * self.noise_floor + self.alpha * e2500
                return None

        else:
            # Active beep in progress: append frame
            self._current_run_frames.append(frame)
            self.active_frames = self._current_run_frames

            # END condition: all mics are < 2x noise floor for 2 consecutive frames (40 ms)
            all_quiet = bool(np.all(e2500 < 2.0 * self.noise_floor))

            if all_quiet:
                self._consecutive_quiet += 1
                if self._consecutive_quiet >= 2:
                    # Beep ENDs
                    self.is_beep_active = False
                    self._consecutive_quiet = 0

                    raw_run = list(self._current_run_frames)
                    # The 2 trailing quiet frames confirmed beep completion;
                    # trim them to isolate the active acoustic pulse
                    if len(raw_run) >= 2:
                        active_beep_frames = raw_run[:-2]
                    else:
                        active_beep_frames = raw_run

                    # Fallback if pulse was very short
                    if not active_beep_frames:
                        active_beep_frames = raw_run

                    self.active_frames = active_beep_frames
                    self._current_run_frames = []

                    self._event_counter += 1
                    event_id = f"ev_{self._event_counter}"

                    features = extract_spatial_features(active_beep_frames, self.noise_floor)
                    event = BeepEvent(
                        frames=active_beep_frames,
                        noise_floor=self.noise_floor.copy(),
                        features=features,
                        raw_frames=raw_run,
                        event_id=event_id,
                    )
                    self.last_beep = event
                    self.completed_beeps.append(event)
                    return event
            else:
                self._consecutive_quiet = 0

            return None

    # Aliases
    feed_line = process_line
    feed_frame = process_frame
    process = process_line

    def reset(self) -> None:
        """Reset state processor to uninitialized state."""
        self.noise_floor = None
        self.is_beep_active = False
        self._consecutive_quiet = 0
        self.active_frames.clear()
        self._current_run_frames.clear()
        self.blank_until_ms = None
        self._blank_pending_ms = None
        self._blank_frames_remaining = 0
        self.last_ms = None
        self.last_beep = None
        self.completed_beeps.clear()
