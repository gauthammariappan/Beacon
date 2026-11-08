# Beacon v2.1 · System Status & Feature Implementation Summary

> **Acoustic Localization & Direction Finding for Unmonitored Data Center Equipment**  
> *Target: HackUTD NMC² Track · Status: Production-Ready (Hardware Integrated & Verified)*

---

## 1. Executive Summary

Beacon v2.1 solves the acoustic blindness problem in loud (70–80+ dB) data center environments. When an unmonitored UPS or PDU starts beeping, 3 overhead microphones hung across an 85 cm aisle listen at 2500 Hz, localize the offending rack among 5 candidate server racks (A, B, C, D, E) via an acoustic ML model, decode the alarm cadence rhythm, swing a pan laser turret at the rack, and instantly push an actionable alert to technician smartphones with a one-touch **Acknowledge** button.

All core layers (Layers 1 through 7) have been implemented, connected, and verified with **28/28 passing automated tests**.

---

## 2. Feature Implementation Matrix

| Architecture Layer | Component | Status | Key Implemented Features |
|---|---|:---:|---|
| **Layer 1: Firmware** | `firmware/beacon_pico/` | **Complete** | • RP2350/RP2040 firmware running 16 kHz sampling on 3 ADC channels.<br>• 256-sample Goertzel filter for 2500 Hz target, 2000 Hz low ref, 3000 Hz high ref.<br>• Microsecond-precise 50 Hz frame output: `E,<ms>,L25,M25,R25,...`<br>• Serial command parser: `AIM,<pan>\n` (supports both absolute 20°..180° and relative -45°..+45°) and `LASER,1` / `LASER,0`. |
| **Layer 2: Ingest** | `beacon/server.py`<br>`tools/record.py` | **Complete** | • USB CDC auto-detection for Pico on `/dev/cu.usbmodem*`, `/dev/tty.usbmodem*`, `/dev/ttyACM*`, `/dev/ttyUSB*` at 115200 baud.<br>• **Live Hardware First**: `replay_paused = True` by default; strictly listens to physical serial port.<br>• Safe, non-blocking asynchronous executor ingestion.<br>• Calibration recorder CLI (`tools/record.py`) with auto-flush on Ctrl+C. |
| **Layer 3: Signal** | `beacon/signal.py`<br>`beacon/features.py` | **Complete** | • Running noise floor tracking with EWMA ($\alpha=0.02$) per mic.<br>• **Noise floor freezing** during active beeps so long tones aren't absorbed.<br>• Purity metric calculation: $E_{2500} / \text{avg}(E_{2000}, E_{3000})$ with epsilon guard.<br>• **Tuned Schmitt trigger**: START at $>4.0\times$ floor + purity $>2.0$; END at $<2.0\times$ floor for 2 frames (40 ms).<br>• Hardware potentiometer skew cancellation via noise-floor-normalized spatial energies.<br>• 350 ms acoustic blanking window to discard servo noise. |
| **Layer 4: Brain 1 (Location)** | `beacon/location_model.py`<br>`tools/train_location.py` | **Complete** | • Evaluated on real recorded dataset: Random Forest achieves **100.0% accuracy** on Session 2 test set.<br>• Model weights exported to `artifacts/location_model.joblib`.<br>• Benchmark metrics & confusion matrices exported to `artifacts/location_metrics.json`.<br>• Exponential running vote smoothing ($V_t = 0.3 P_t + 0.7 V_{t-1}$).<br>• Uncertainty gate: flags `uncertain: True` when max probability $<0.60$. |
| **Layer 4: Brain 2 (Cadence)** | `beacon/incidents.py`<br>`beep_model/` | **Complete** | • `CadenceTracker`: Evaluates inter-beep intervals and pulse durations using acoustic frame timestamps.<br>• Continuous tone ($>600\text{ ms}$) $\to$ **UPS Overload (P3)**.<br>• Rapid cadence ($<1.0\text{ s}$ gap) $\to$ **UPS Low Battery (P2)**.<br>• Bursts with pause $\to$ **UPS On Battery (P1)**. |
| **Layer 5: Action & Actuation** | `beacon/incidents.py`<br>`beacon/server.py` | **Complete** | • State Machine: `DETECTED` $\to$ `LOCATED` $\to$ `IDENTIFIED` $\to$ `ACKNOWLEDGED` $\to$ `CLEARED`.<br>• AimController: loads servo angles from `config/aim_points.json`, dispatches `AIM,<pan>\n` + `LASER,1\n`.<br>• Non-blocking 5.0 s async timer turns off laser with `LASER,0\n`.<br>• 10-second silence timeout automatically clears resolved alarms. |
| **Layer 6: API** | `beacon/server.py` | **Complete** | • FastAPI backend with full CORS support.<br>• `WS /live`: 10 Hz live mic levels streaming + instant push notifications on state changes.<br>• `GET /layout`: Physical rack geometry & mic positions (`rack_layout.json`).<br>• `POST /incidents/{id}/ack`: Flips state to `ACKNOWLEDGED` and broadcasts immediately.<br>• `GET /model/location/metrics`: Serves Brain 1 spatial location benchmarks.<br>• `GET /model/rhythm/metrics`: Serves Brain 2 temporal cadence benchmarks.<br>• `POST /demo/replay/toggle` & `POST /demo/trigger/{rack}/{pattern}`: Pitch demonstration controls. |
| **Layer 7: Presentation** | `web/index.html`<br>`web/app.js` | **Complete** | • **Responsive Bifurcation**: Desktop renders NOC Dashboard; Mobile renders strictly Technician Pager View.<br>• **Live Tab**: Top-down SVG map with target rack glow, animated laser beam aiming from turret (450, 270), 10 Hz mic level bars.<br>• **Dual-Brain Model Tab**: Brain 1 (Spatial Location) + Brain 2 (Alarm Rhythm) confusion matrices and metrics.<br>• **Setup Tab**: Servo pan jog controls (-45° to +45°), keyboard arrow navigation, laser toggle, rack angle locking, 350 ms blanking test.<br>• **Live QR Code**: Dynamically rendered on NOC dashboard using detected LAN IP for seamless mobile pager handoff.<br>• **Pager View**: Full-screen high-contrast alert card + giant one-touch `ACKNOWLEDGE` button with instant WebSocket sync. |

---

## 3. Real Hardware Verification

### A. Live Serial Communication
* **Port auto-detection**: Scans `/dev/cu.usbmodem*`, `/dev/tty.usbmodem*`, `/dev/ttyACM*`, `/dev/ttyUSB*` at 115200 baud.
* **Auto-reconnect**: If Pico USB is unplugged and reconnected, the background loop safely resets buffers and re-establishes streaming.
* **Replay Isolation**: `replay_paused = True` by default so pitch demos run strictly from real hardware telemetry without background synthetic drift.

### B. Schmitt Trigger Tuning on Real Acoustics
* `recordings/session1_train.csv`: 240/240 events correctly segmented (40 per rack A-E and NONE).
* `recordings/session2_test.csv`: 150/150 events correctly segmented (25 per rack A-E and NONE).
* Thresholds: `snr_threshold = 4.0`, `purity_threshold = 2.0`. Broadband ambient noise (purity $\approx 1.0$) causes zero false triggers.

### C. Physical Table ML Weights
* Random Forest model re-trained on real recorded data and saved to `artifacts/location_model.joblib`.
* Outperforms baselines:
  - Loudest Mic: 50.00%
  - Weighted Centroid: 49.33%
  - **Random Forest: 100.00%**

---

## 4. Verification & Automated Test Status

All 28 automated tests pass cleanly in under 0.20s:
```bash
python3 -m unittest discover
# Ran 28 tests in 0.168s · OK
```

### Verified Test Suites:
1. `test_beacon.py` (10 tests):
   - 50 Hz serial line parsing (`E,<ms>,L25,M25,R25,...`).
   - Running noise floor EWMA update and freeze during active beeps.
   - Purity calculation and division-by-zero safeguard.
   - Schmitt trigger hysteresis (START at $>4.0\times$, END at $<2.0\times$ for 2 frames).
   - 350 ms acoustic blanking window.
   - Vectorized 19-element spatial feature extraction with potentiometer normalization.
2. `test_location.py` (5 tests):
   - Model artifact loading from `artifacts/location_model.joblib`.
   - Real hardware dataset segmentation (240 train events, 150 test events).
   - Baseline performance benchmarks (Loudest Mic vs. Centroid vs. Random Forest).
   - Exponential vote smoothing and uncertainty thresholding ($<0.60$).
3. `test_record.py` (5 tests):
   - USB CDC serial auto-detection for macOS/Linux (`/dev/cu.usbmodem*`, `/dev/tty.usbmodem*`).
   - Session CSV file path resolution (train vs. test).
   - Real-time line parsing and malformed serial rejection.
   - CSV header initialization and non-duplication.
   - Interactive prompt and `KeyboardInterrupt` flush handling.
4. `test_server_and_incidents.py` (8 tests):
   - `IncidentManager` lifecycle: `DETECTED` $\to$ `LOCATED` $\to$ `IDENTIFIED` $\to$ `ACKNOWLEDGED` $\to$ `CLEARED`.
   - State transition locking (active `IDENTIFIED`/`ACKNOWLEDGED` incidents cannot be overwritten by stray frames).
   - AimController actuation (`AIM,<pan>`, `LASER,1`, 5.0 s async timer) and pan angle lookup.
   - Dual-Brain REST endpoints: `GET /model/location/metrics`, `GET /model/rhythm/metrics`.
   - Pitch demo endpoints: `POST /demo/replay/toggle`, `POST /demo/trigger/{rack}/{pattern}`.
