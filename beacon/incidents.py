"""Incident management state machine and cadence tracking for Beacon v2.1."""

from __future__ import annotations

import time
from enum import Enum
from typing import Any


class IncidentState(str, Enum):
    """Incident lifecycle states."""
    DETECTED = "DETECTED"
    LOCATED = "LOCATED"
    IDENTIFIED = "IDENTIFIED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CLEARED = "CLEARED"


class Incident:
    """Represents a data center acoustic alarm incident."""

    def __init__(
        self,
        incident_id: str,
        initial_state: IncidentState = IncidentState.DETECTED,
        rack: str = "UNKNOWN",
        confidence: float = 0.0,
        alarm: dict[str, Any] | None = None,
        runner_up: dict[str, Any] | None = None,
        first_heard: float | None = None,
    ) -> None:
        self.id: str = incident_id
        self.state: IncidentState = initial_state
        self.rack: str = rack
        self.confidence: float = float(confidence)
        self.alarm: dict[str, Any] = alarm or {}
        self.runner_up: dict[str, Any] = runner_up or {}
        now = time.time() if first_heard is None else float(first_heard)
        self.first_heard: float = now
        self.last_heard: float = now
        self.beeps_count: int = 1

    def to_dict(self) -> dict[str, Any]:
        """Generate JSON dict matching Beacon v2.1 data contract.

        Contract:
        {"id": "inc_1", "state": "IDENTIFIED", "rack": "B", "confidence": 0.89, "alarm": {"meaning": "UPS On Battery"}}
        """
        data: dict[str, Any] = {
            "id": self.id,
            "state": self.state.value,
            "rack": self.rack,
            "confidence": round(self.confidence, 4),
            "alarm": self.alarm if self.alarm else {"meaning": "Identifying alarm..."},
        }
        if self.runner_up:
            data["runner_up"] = self.runner_up
        data["beeps"] = self.beeps_count
        data["first_heard_ts"] = self.first_heard
        data["last_heard_ts"] = self.last_heard
        return data


class CadenceTracker:
    """Brain 2 cadence decoder: matches inter-beep timing and duration to identify alarm rhythms."""

    def __init__(self) -> None:
        self.beep_timestamps: list[float] = []
        self.beep_durations: list[float] = []

    def reset(self) -> None:
        self.beep_timestamps.clear()
        self.beep_durations.clear()

    def feed_beep(self, event: Any = None, timestamp: float | None = None) -> dict[str, Any] | None:
        """Feed a detected beep into the cadence tracker.

        Returns alarm dict if cadence is locked, or None if still accumulating.
        """
        if event is not None and hasattr(event, "get") and event.get("t_end"):
            now = float(event.get("t_end"))
        elif timestamp is not None:
            now = float(timestamp)
        else:
            now = time.time()

        dur_ms = 200.0
        if event is not None:
            if isinstance(event, dict):
                dur_ms = float(event.get("duration_ms", 200.0))
            elif hasattr(event, "features") and event.features is not None and len(event.features) > 18:
                dur_ms = float(event.features[18])

        self.beep_timestamps.append(now)
        self.beep_durations.append(dur_ms)

        # 1. Steady continuous tone (> 600 ms) locks immediately
        if dur_ms >= 600.0:
            return {
                "meaning": "UPS Overload",
                "device": "UPS",
                "pattern": "P3",
                "action": "Reduce load immediately",
            }

        # 2. If 2 or more beeps observed, check intervals
        if len(self.beep_timestamps) >= 2:
            gaps = [
                self.beep_timestamps[i] - self.beep_timestamps[i - 1]
                for i in range(1, len(self.beep_timestamps))
            ]
            last_gap = gaps[-1]

            # Rapid beeping (< 1.0 s gap)
            if last_gap < 1.0:
                return {
                    "meaning": "UPS Low Battery",
                    "device": "UPS",
                    "pattern": "P2",
                    "action": "Shed load or start graceful shutdown",
                }

            # Standard battery cadence (burst of beeps, e.g. every 2-5 s in demo)
            return {
                "meaning": "UPS On Battery",
                "device": "UPS",
                "pattern": "P1",
                "action": "Check upstream power / generator",
            }
        if len(self.beep_timestamps) >= 2:
            gaps = [
                self.beep_timestamps[i] - self.beep_timestamps[i - 1]
                for i in range(1, len(self.beep_timestamps))
            ]
            last_gap = gaps[-1]

            # Rapid beeping (< 1.0 s gap)
            if last_gap < 1.0:
                return {
                    "meaning": "UPS Low Battery",
                    "device": "UPS",
                    "pattern": "P2",
                    "action": "Shed load or start graceful shutdown",
                }

            # Standard battery cadence (burst of beeps, e.g. every 2-5 s in demo)
            return {
                "meaning": "UPS On Battery",
                "device": "UPS",
                "pattern": "P1",
                "action": "Check upstream power / generator",
            }

        return None


class IncidentManager:
    """State machine managing alarm incidents for Beacon v2.1.

    States:
      DETECTED → LOCATED (after 1st beep spatial lock)
               → IDENTIFIED (after teammate's temporal model locks cadence)
               → ACKNOWLEDGED (manual trigger)
               → CLEARED (10 s silence timeout)
    """

    def __init__(self, silence_timeout_s: float = 10.0) -> None:
        self.silence_timeout_s: float = float(silence_timeout_s)
        self.active_incident: Incident | None = None
        self.history: list[Incident] = []
        self._incident_counter: int = 0
        self.cadence_tracker: CadenceTracker = CadenceTracker()

    def feed_beep(
        self,
        location_result: dict[str, Any] | None = None,
        alarm_result: dict[str, Any] | None = None,
        event: Any | None = None,
        timestamp: float | None = None,
    ) -> Incident | None:
        """Feed a detected beep event into the incident state machine.

        Parameters
        ----------
        location_result : dict, optional
            Prediction from LocationClassifier (Brain 1).
            Contains 'rack', 'confidence', 'uncertain', 'runner_up'.
        alarm_result : dict, optional
            Pre-computed alarm info from temporal model (Brain 2).
        event : Any, optional
            Raw BeepEvent from SignalProcessor.
        timestamp : float, optional
            Current timestamp in seconds (default: time.time()).

        Returns
        -------
        Incident | None
            The updated active incident, or None if event was rejected (e.g. NONE).
        """
        now = time.time() if timestamp is None else float(timestamp)

        # Discard false-trigger events classified as NONE
        if location_result is not None:
            predicted_rack = location_result.get("rack", "NONE")
            if predicted_rack == "NONE":
                return None

        # Check if cadence tracker can identify alarm if not explicitly provided
        if alarm_result is None:
            alarm_result = self.cadence_tracker.feed_beep(event, timestamp=now)

        # Check for timeout on prior incident if rack changed or idle
        self.check_timeout(current_time=now)

        # Create or update incident
        if self.active_incident is None:
            self._incident_counter += 1
            inc_id = f"inc_{self._incident_counter}"

            # Step 1: Initial state is DETECTED
            incident = Incident(
                incident_id=inc_id,
                initial_state=IncidentState.DETECTED,
                first_heard=now,
            )
            self.active_incident = incident
        else:
            incident = self.active_incident
            incident.beeps_count += 1
            incident.last_heard = now

        # Step 2: Spatial location lock -> LOCATED
        if location_result is not None:
            # Lock rack once IDENTIFIED or ACKNOWLEDGED to prevent replay/noise overwrites
            if incident.state in (IncidentState.DETECTED, IncidentState.LOCATED):
                incident.rack = location_result.get("rack", incident.rack)
                incident.confidence = float(location_result.get("confidence", incident.confidence))
            if "runner_up" in location_result:
                incident.runner_up = location_result["runner_up"]

            # Transition DETECTED -> LOCATED after 1st beep spatial lock
            if incident.state == IncidentState.DETECTED:
                incident.state = IncidentState.LOCATED

        # Step 3: Cadence lock -> IDENTIFIED
        if alarm_result is not None and "meaning" in alarm_result:
            # Transition to IDENTIFIED if not already ACKNOWLEDGED or CLEARED
            if incident.state in (IncidentState.DETECTED, IncidentState.LOCATED):
                incident.alarm = alarm_result
                incident.state = IncidentState.IDENTIFIED

        return incident

    def check_timeout(
        self,
        current_time: float | None = None,
        timeout_seconds: float | None = None,
    ) -> Incident | None:
        """Check if 10 s silence timeout has elapsed; if so, transitions to CLEARED.

        Returns
        -------
        Incident | None
            The cleared incident if timeout expired; None otherwise.
        """
        if self.active_incident is None:
            return None

        now = time.time() if current_time is None else float(current_time)
        timeout = self.silence_timeout_s if timeout_seconds is None else float(timeout_seconds)

        elapsed_silence = now - self.active_incident.last_heard
        if elapsed_silence >= timeout:
            cleared_incident = self.active_incident
            cleared_incident.state = IncidentState.CLEARED
            self.history.append(cleared_incident)
            self.active_incident = None
            self.cadence_tracker.reset()
            return cleared_incident

        return None

    def acknowledge(self, incident_id: str | None = None) -> Incident | None:
        """Manually trigger acknowledgement of an incident (ACKNOWLEDGED state).

        Parameters
        ----------
        incident_id : str, optional
            ID of the incident to acknowledge. If None, acknowledges active incident.

        Returns
        -------
        Incident | None
            The acknowledged incident, or None if not found.
        """
        # 1. Check active incident
        if self.active_incident is not None:
            if incident_id is None or self.active_incident.id == incident_id:
                if self.active_incident.state != IncidentState.CLEARED:
                    self.active_incident.state = IncidentState.ACKNOWLEDGED
                    return self.active_incident

        # 2. Check history if specific id requested
        if incident_id is not None:
            for inc in reversed(self.history):
                if inc.id == incident_id:
                    if inc.state != IncidentState.CLEARED:
                        inc.state = IncidentState.ACKNOWLEDGED
                    return inc

        return None

    def get_active_incident(self) -> Incident | None:
        """Return the current active incident, if any."""
        return self.active_incident

    def get_history(self) -> list[dict[str, Any]]:
        """Return list of historical incident JSON dicts."""
        return [inc.to_dict() for inc in self.history]

    def reset(self) -> None:
        """Reset state machine."""
        if self.active_incident is not None:
            self.active_incident.state = IncidentState.CLEARED
            self.history.append(self.active_incident)
            self.active_incident = None
        self.cadence_tracker.reset()

