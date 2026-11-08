# Beacon v2.1 — Senior Staff Engineering Red Team Audit
**Project**: Beacon v2.1 · Real-Time Acoustic Localization & Incident Response  
**Track**: NMC² Data Center Acoustic Tracking (HackUTD)  
**Date**: November 8, 2026  
**Auditor**: Senior Staff Systems & ML Infrastructure Engineer  
**Status**: **GO (APPROVED FOR JUDGE PITCH)**  

---

## 1. Project Directory & Component Functional Map

```
Beeper/
├── ARCHITECTURE.md                 # 5-Layer System Specification & Data Contract
├── STATUS.md                       # Implementation Status & Ground Truth Sync
├── AUDIT_REPORT.md                 # Senior Staff Red Team Technical Audit (This Document)
├── aim_points.json                 # Turret relative aim offsets
├── rack_layout.json                # Physical data hall aisle geometry (85 cm span)
│
├── config/
│   └── aim_points.json             # Absolute pan servo calibration angles (A=35°, B=62°, C=90°, D=118°, E=145°)
│
├── firmware/
│   └── beacon_pico/
│       └── beacon_pico.ino         # Raspberry Pi Pico 2W firmware (16 kHz Goertzel burst, 50 Hz telemetry)
│
├── beacon/                         # Core Python Backend Package
│   ├── __init__.py                 # Package init
│   ├── signal.py                   # Layer 3 DSP: EWMA noise floor, Schmitt trigger, acoustic blanking
│   ├── features.py                 # Layer 3 Features: 19 vectorized spatial features (noise-normalized)
│   ├── location_model.py           # Layer 4 Brain 1: Spatial Location Random Forest & running vote smoothing
│   ├── incidents.py                # Layer 4 Brain 2 + Layer 5: Cadence Tracker & Incident State Machine
│   └── server.py                   # Layer 2/5: FastAPI, 10Hz WS, async aim controller, replay simulator
│
├── beep_model/                     # Teammate's Temporal Rhythm Model (Brain 2)
│   ├── artifacts/
│   │   ├── metrics.json            # 12-class rhythm metrics (99.0% Val Macro F1, 0.0% false alarms)
│   │   └── model.joblib            # Trained rhythm classifier
│   └── train.py                    # Temporal rhythm trainer
│
├── artifacts/                      # Brain 1 Trained Model Artifacts
│   ├── location_metrics.json       # 3-method benchmark (Loudest 51.7% vs Centroid 51.0% vs RF 100.0%)
│   └── location_model.joblib       # Winning Random Forest pipeline
│
├── recordings/                     # Physical Calibration Datasets
│   ├── session1_train.csv          # Training session dataset
│   └── session2_test.csv           # Out-of-session evaluation dataset
│
├── beeps/                          # Audio validation waveforms (P1, P2, P3, datacenter fan noise)
│
├── tools/                          # Command-Line Tools
│   ├── record.py                   # Hardware calibration CLI recorder for Pico USB serial
│   ├── train_location.py           # Brain 1 model training & baseline evaluation benchmark
│   └── generate_beeps.py           # Synthetic alarm pulse audio waveform generator
│
├── web/                            # Frontend Web Application
│   ├── index.html                  # Responsive NOC Dashboard & Mobile Technician Pager View
│   └── app.js                      # WebSocket client, dual-brain metrics visualizer, QR generator
│
└── tests/ (Root Test Suite)
    ├── test_beacon.py              # Unit tests for DSP, Schmitt trigger, blanking, and 19 features
    ├── test_location.py            # Unit tests for LocationClassifier and running vote smoothing
    ├── test_record.py              # Unit tests for CLI recorder, format validation, and CSV safety
    └── test_server_and_incidents.py # Unit tests for FastAPI REST/WS, state machine, and aim controller
```

---

## 2. Red Team Audit: Critical Failure Point Analysis

### 2.1 Concurrency & Event Loop (`beacon/server.py`)
| Audit Check | Status | Technical Assessment |
| :--- | :--- | :--- |
| **50 Hz Ingestion Non-Blocking** | **PASS** | `run_serial_reader()` executes `ser.readline()` via `await loop.run_in_executor(None, ser.readline)` in a thread pool executor. The replay simulator yields via `await asyncio.sleep(0.02)`. Neither stalls the event loop. |
| **5-Second Laser Timer Non-Blocking** | **PASS** | `aim_turret_at_rack()` invokes `asyncio.create_task(_turn_off_laser())`. The task is backgrounded immediately without being awaited; incoming mic frames and 10 Hz WebSocket broadcasts proceed uninterrupted. |
| **Task Cancellation Hygiene** | **PASS** | Existing laser off tasks are safely cancelled before spawning a new one if target rack updates, preventing timer collision or dangling tasks. |

### 2.2 DSP & Feature Math (`beacon/signal.py` / `beacon/features.py`)
| Audit Check | Status | Technical Assessment |
| :--- | :--- | :--- |
| **EWMA Noise Floor Freezing** | **PASS** | In `SignalProcessor.process_frame()`, when `self.is_beep_active` is `True`, noise floor EWMA accumulation is completely bypassed (`self.noise_floor` remains frozen). Only quiet inter-pulse intervals update the floor. |
| **Hardware Potentiometer Normalization** | **PASS** | `extract_spatial_features()` computes `normalized_energy = avg_2500 / np.maximum(nf, 1e-6)`. Both `share` and `log_ratio` features are strictly derived from `normalized_energy`, neutralizing hardware potentiometer gain skew. |
| **Divide-by-Zero & Log-Domain Safety** | **PASS** | `compute_purity()` guards denominator with `np.maximum(avg_side, 1e-9)`. `log_ratio` clips normalized energy with `np.maximum(normalized_energy, 1e-6)` and outputs are clipped to `[-10.0, 10.0]`. No NaN, inf, or zero-division exceptions can occur. |
| **Acoustic Blanking Window** | **PASS** | Frames arriving where `frame["t_ms"] < self.blank_until_ms` are dropped immediately without updating Schmitt triggers or noise floors, absorbing servo acoustic noise. |

### 2.3 State Machine Integrity (`beacon/incidents.py`)
| Audit Check | Status | Technical Assessment |
| :--- | :--- | :--- |
| **Lock Protection on IDENTIFIED / ACKNOWLEDGED** | **PASS (Fixed)** | If free-running replay feeds subsequent racks while an incident is `IDENTIFIED` or `ACKNOWLEDGED`, `feed_beep()` locks the active incident rack and alarm meaning. Only after the 10-second silence timeout clears the incident can a new rack be assigned. |
| **Cadence Tracker Deduplication** | **PASS (Fixed)** | `CadenceTracker.feed_beep()` now prioritizes acoustic frame timestamps (`event.get("t_end")`) over wall-clock `time.time()`, preventing rapid replay frames from being misinterpreted as rapid P2 beeping. |
| **WebSocket JSON Contract Match** | **PASS** | The emitted payload strictly conforms to contract: `{"id": str, "state": str, "rack": str, "confidence": float, "alarm": {"meaning": str, ...}}`. |

### 2.4 Frontend Resilience (`web/app.js` & `web/index.html`)
| Audit Check | Status | Technical Assessment |
| :--- | :--- | :--- |
| **WebSocket Auto-Reconnect** | **PASS** | Implements exponential backoff reconnect (`1.0s`, `1.5s`, `2.25s` up to `5.0s max`) on `ws.onclose` and `ws.onerror`. Automatically recovers if Uvicorn restarts. |
| **DOM Ready & QR Code Safety** | **PASS** | Script initialization checks `document.readyState` and attaches to `DOMContentLoaded`. Canvas and container queries use null guards (`if (canvas) ...`) preventing null-pointer crashes. |
| **Local Network IP Resolution** | **PASS** | Resolves actual local LAN IP (e.g., `10.173.171.63`) via backend `GET /layout` so phones scanning the QR code reach the laptop rather than failing on `localhost`. |
| **Missing Metrics JSON Tolerance** | **PASS** | `Promise.allSettled` in `fetchModelMetrics()` gracefully handles missing `metrics.json` files with static fallbacks, never crashing the dashboard. |

---

## 3. Checklist of Remediations Applied

### CRITICAL SHOW-STOPPERS (Resolved)

1. **State Machine Rack Mutation on Active Acknowledged Incidents**:
   - **Risk**: Free-running CSV replay loop could overwrite `incident.rack` while a judge was looking at an acknowledged incident.
   - **Resolution Applied in [`beacon/incidents.py`](file:///Users/kingebenezer/Desktop/Beeper/beacon/incidents.py)**:
     ```python
     # Lock rack once IDENTIFIED or ACKNOWLEDGED to prevent replay/noise overwrites
     if incident.state in (IncidentState.DETECTED, IncidentState.LOCATED):
         incident.rack = location_result.get("rack", incident.rack)
         incident.confidence = float(location_result.get("confidence", incident.confidence))
     ```

2. **Simulation Wall-Clock Cadence Timestamp Distortion**:
   - **Risk**: Processing stored frames in fast-replay caused `feed_beep()` to record wall-clock elapsed time (~0.001s) instead of acoustic frame time, misclassifying P1 ("On Battery") as P2 ("Low Battery").
   - **Resolution Applied in [`beacon/incidents.py`](file:///Users/kingebenezer/Desktop/Beeper/beacon/incidents.py)**:
     ```python
     if event is not None and hasattr(event, "get") and event.get("t_end"):
         now = float(event.get("t_end"))
     elif timestamp is not None:
         now = float(timestamp)
     else:
         now = time.time()
     ```

3. **Deterministic Reset on Demo Pitch Triggers**:
   - **Risk**: Repeated demo triggers (`POST /demo/trigger/{rack}/{pattern}`) retained previous active incident state.
   - **Resolution Applied in [`beacon/server.py`](file:///Users/kingebenezer/Desktop/Beeper/beacon/server.py)**:
     ```python
     signal_processor.reset()
     location_classifier.reset()
     incident_manager.reset()
     global last_aimed_rack
     last_aimed_rack = None
     ```

---

### MINOR WARNINGS & PITCH RECOMMENDATIONS

1. **Background Replay during Live Pitch**:
   - *Recommendation*: During the 2-minute live pitch, keep auto-replay **PAUSED** (`replay_paused = True`) or use the keyboard shortcuts `1`–`5` / `Q`–`E` to trigger clean deterministic alarm events.
2. **Wi-Fi Subnet Matching for Mobile Pager**:
   - *Recommendation*: Ensure the judge's phone is connected to the same local Wi-Fi network (or laptop personal hotspot) so the `http://<LAN-IP>:8000/?mobile=1` QR code connects immediately.

---

## 4. Verification Test Suite Run

```text
...........................
----------------------------------------------------------------------
Ran 27 tests in 0.066s

OK
```

- **Layer 3 Signal & DSP**: 8 tests passed (`test_beacon.py`)
- **Layer 4 Location Model**: 7 tests passed (`test_location.py`)
- **Hardware Recorder CLI**: 4 tests passed (`test_record.py`)
- **FastAPI, Incidents, & Aim Controller**: 8 tests passed (`test_server_and_incidents.py`)

---

## 5. Final Senior Staff Engineer Verdict

### **VERDICT: GO (APPROVED FOR SUBMISSION & PITCH)**
The Beacon v2.1 codebase satisfies real-time acoustic constraints, preserves strict architectural boundaries between Layer 3 (DSP), Layer 4 (Dual Brains), and Layer 5 (State Machine/Actuation), executes non-blocking asynchronous event handling, and provides resilient responsive bifurcation for both NOC Dashboard and Mobile Technician Pager.

