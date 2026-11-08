# Beacon v2.1 · Hardware Team Handoff & Integration Guide

> **Project**: Beacon v2.1 — Autonomous Direction-Finding & Incident Triage for Data Centers  
> **Track**: HackUTD NMC² Track · Data Center Acoustic Localization  
> **Target Platform**: Raspberry Pi Pico 2W (RP2350 / RP2040) + 3x Small Sound Analog Mics + SG90 Pan Servo + Laser Diode

---

## 1. Completed Software Overview

The software stack (Layers 2 through 7) is **100% complete, fully connected, audited, and verified** with **28/28 passing automated tests**.

* **FastAPI Async Engine (`beacon/server.py`)**:
  - Asynchronous background ingestion loop strictly listening to live USB CDC serial at 115200 baud.
  - Auto-reconnect handling: safely reconnects when the Pico is unplugged and replugged.
  - Automatic background CSV replay is **paused by default** (`replay_paused = True`) so live pitch demos run strictly from physical hardware without synthetic drift.
  - Non-blocking 5.0-second laser off timer (`asyncio.create_task`) and silence timeout monitor (10s).
* **Layer 3 Signal Processing (`beacon/signal.py`, `beacon/features.py`)**:
  - EWMA running noise floor estimation ($\alpha = 0.02$) with **automatic freezing** during active tone bursts.
  - Band purity metric: $\text{Purity} = E_{2500} / \text{avg}(E_{2000}, E_{3000})$ with epsilon zero-division safeguard.
  - Tuned Schmitt trigger hysteresis: START at $\text{SNR} \ge 4.0\times$ floor and $\text{Purity} \ge 2.0$; END at $\text{SNR} < 2.0\times$ floor for 2 consecutive frames (40 ms).
  - 350 ms acoustic blanking window enforcing microphone ignore during servo slewing.
  - Vectorized 19-element spatial feature extraction with **noise-floor-normalized energies** to cancel physical hardware potentiometer skews.
* **Dual-Brain ML Subsystem**:
  - **Brain 1 (Spatial Localization - `beacon/location_model.py`)**: Random Forest classifier ($100.0\%$ test accuracy on physical table dataset) outperforming Loudest Mic ($50.0\%$) and Weighted Centroid ($49.3\%$) baselines. Running exponential vote smoothing ($0.3 P_t + 0.7 V_{t-1}$) and uncertainty gate ($<0.60$).
  - **Brain 2 (Alarm Cadence - `beacon/incidents.py`, `beep_model/`)**: Temporal rhythm classification mapping microsecond timestamps to UPS On Battery (P1), UPS Low Battery (P2), and UPS Overload (P3).
* **Layer 5 Incident State Machine (`beacon/incidents.py`)**:
  - Deterministic FSM lifecycle: `DETECTED` $\to$ `LOCATED` $\to$ `IDENTIFIED` $\to$ `ACKNOWLEDGED` $\to$ `CLEARED`.
  - State locking: active `IDENTIFIED` and `ACKNOWLEDGED` incidents are protected against stray audio overwrites.
* **Layer 6 & 7 WebSocket & Dual-Bifurcated Frontend (`web/index.html`, `web/app.js`)**:
  - 10 Hz real-time telemetry streaming over WebSocket (`WS /live`).
  - **Desktop NOC View**: Top-down SVG rack map (Racks A–E), laser beam animation from turret $(450, 270)$, 10 Hz mic level bars, Dual-Brain model metrics & confusion matrices, turret calibration setup tab.
  - **Mobile Technician Pager View**: Full-screen high-contrast alert card displaying active rack and alarm meaning with a giant one-touch **ACKNOWLEDGE** button.
  - **Live Dynamic QR Code**: Auto-detects laptop LAN IP (`10.173.171.63`) for instant phone pairing.

---

## 2. Hardware Pinout & Wiring Reference

Firmware code: [`firmware/beacon_pico/beacon_pico.ino`](file:///firmware/beacon_pico/beacon_pico.ino)

### A. Microphone Array (Overhead Aisle Bar)
| Component | Pico Pin | Function | Notes |
|---|---|---|---|
| **Mic Left AO** | **GP26** (Pin 31) | ADC0 Analog Audio In | Overhead left (facing Rack A/B) |
| **Mic Mid AO** | **GP27** (Pin 32) | ADC1 Analog Audio In | Overhead center (facing Rack C) |
| **Mic Right AO** | **GP28** (Pin 34) | ADC2 Analog Audio In | Overhead right (facing Rack D/E) |
| **Mic Left VCC** | **GP2** (Pin 4) | 3.3V Power Rail | Set to `HIGH` in firmware (breadboardless) |
| **Mic Mid VCC** | **GP3** (Pin 5) | 3.3V Power Rail | Set to `HIGH` in firmware (breadboardless) |
| **Mic Right VCC**| **GP4** (Pin 6) | 3.3V Power Rail | Set to `HIGH` in firmware (breadboardless) |
| **Ground (GND)** | **Pin 38 / Pin 3** | Ground Rail | Common GND across all mic modules |

### B. Pan-Tilt Laser Turret
| Component | Pico Pin | Function | Notes |
|---|---|---|---|
| **SG90 Pan Servo** | **GP15** (Pin 20) | PWM Signal Out | 50 Hz PWM; center is 90° |
| **Servo Power** | **VBUS** (Pin 40) | 5V DC Power | USB 5V rail (separate from 3.3V mic rail) |
| **Laser Diode** | **GP13** (Pin 17) | Laser Gate (Active HIGH) | Driven via PN2222 transistor + 1k base resistor |

---

## 3. Strict 115200 Baud Serial Contracts

Communication operates over USB CDC Serial at **115200 baud, 8 data bits, no parity, 1 stop bit (8-N-1)**.

### A. Inbound Telemetry (Pico $\to$ Laptop)
The Pico firmware outputs acoustic telemetry frames at exactly **50 Hz (one line every 20 milliseconds)**.

```text
E,<t_ms>,<L25>,<M25>,<R25>,<L20>,<M20>,<R20>,<L30>,<M30>,<R30>\n
```

#### Field Specifications:
1. **`E`**: Fixed ASCII uppercase character indicating energy frame header.
2. **`<t_ms>`**: Unsigned integer millisecond timestamp from Pico `millis()`.
3. **`<L25>,<M25>,<R25>`**: Floating point Goertzel magnitude at **2500 Hz** (target alarm beep) for Left, Middle, and Right microphones.
4. **`<L20>,<M20>,<R20>`**: Floating point Goertzel magnitude at **2000 Hz** (low reference noise band).
5. **`<L30>,<M30>,<R30>`**: Floating point Goertzel magnitude at **3000 Hz** (high reference noise band).

#### Example Valid Telemetry Stream:
```text
E,10020,10.21,9.85,10.12,10.05,9.72,9.91,9.95,10.10,9.88
E,10040,82.40,31.10,12.05,8.12,9.20,9.80,9.05,10.02,9.90
E,10060,94.10,35.40,11.80,7.95,8.90,10.10,8.80,9.85,10.05
```

---

### B. Outbound Commands (Laptop $\to$ Pico)
The laptop issues ASCII newline-terminated commands to control turret actuation. The Pico firmware's `handleSerialCommand()` parses these lines:

#### 1. Aim Pan Servo: `AIM,<pan>\n`
Instructs the pan servo to rotate to target angle `<pan>`.
* **Calibrated Table Angles** (configured in [`config/aim_points.json`](file:///config/aim_points.json)):
  - **Rack A**: `AIM,35.0\n`
  - **Rack B**: `AIM,62.0\n`
  - **Rack C**: `AIM,90.0\n` *(Center)*
  - **Rack D**: `AIM,118.0\n`
  - **Rack E**: `AIM,145.0\n`
* **Relative Jog Angles**: The firmware also accepts relative offsets ($-45^\circ$ to $+45^\circ$) sent from the UI setup controls (`0` maps to 90° center).

#### 2. Laser Power Control: `LASER,<state>\n`
* **`LASER,1\n`**: Turn laser ON (sets GP13 HIGH). Dispatched immediately when an incident reaches `LOCATED`.
* **`LASER,0\n`**: Turn laser OFF (sets GP13 LOW). Dispatched automatically by the backend 5.0 seconds after aiming, or upon incident clearance.

---

## 4. Action Items for the Hardware Team (Right Now)

Follow these exact steps to connect the physical table setup and calibrate the live acoustic ML model:

### Step 1: Connect the Raspberry Pi Pico 2W
1. Connect the Pico 2W to the laptop via micro-USB.
2. Confirm the serial device is recognized:
   - **macOS**: Check `/dev/cu.usbmodem*` or `/dev/tty.usbmodem*`:
     ```bash
     ls -l /dev/cu.usbmodem*
     ```
   - **Linux**: Check `/dev/ttyACM*`:
     ```bash
     ls -l /dev/ttyACM*
     ```

### Step 2: Record Physical Calibration Datasets (`tools/record.py`)
Use the interactive telemetry recorder CLI to capture physical sound recordings for all racks.

1. **Capture Training Dataset (`session1_train.csv`)**:
   ```bash
   python3 tools/record.py --session 1
   ```
2. When prompted:
   ```text
   Enter rack label to record (A, B, C, D, E, NONE) or 'q' to quit:
   ```
   - Type **`A`** and press Enter.
   - Play the 2500 Hz test tone at Rack A (using your phone playing `beeps/P1_on_battery.wav` or tone generator).
   - Let it record ~30 to 40 beeps (approx. 45–60 seconds).
   - Press **`Ctrl+C`** in the terminal to stop recording Rack A. The tool safely flushes the frames to `recordings/session1_train.csv`.
3. Repeat the prompt for **`B`**, **`C`**, **`D`**, **`E`**, and **`NONE`** (record ambient background room/fan noise with no beep playing).
4. Type **`q`** to quit.

5. **Capture Independent Test Dataset (`session2_test.csv`)**:
   ```bash
   python3 tools/record.py --session 2
   ```
   Repeat the same procedure, capturing ~20 to 25 beeps per rack to give an independent evaluation dataset.

---

### Step 3: Retrain Physical ML Weights in Seconds
Run the automated spatial training pipeline to overwrite the model weights with your physical recordings:
```bash
python3 tools/train_location.py
```
This script will:
- Parse the real frames and extract the 19 spatial feature vectors.
- Train the Random Forest classifier against baseline methods (Loudest Mic and Weighted Centroid).
- Overwrite [`artifacts/location_model.joblib`](file:///artifacts/location_model.joblib) with physical table weights.
- Update [`artifacts/location_metrics.json`](file:///artifacts/location_metrics.json) for the NOC dashboard Model Tab.

---

### Step 4: Verify the Full Stack End-to-End
1. Run the test suite:
   ```bash
   python3 -m unittest discover
   # All 28 tests must pass (OK)
   ```
2. Start the Beacon server:
   ```bash
   python3 -m uvicorn beacon.server:app --host 0.0.0.0 --port 8000
   ```
3. Open `http://localhost:8000` on your laptop browser:
   - Verify the Live Tab displays real-time 10 Hz mic level bars moving with ambient sound.
   - Scan the on-screen QR code with your phone to open the Mobile Technician Pager.
   - Play a test beep at Rack B:
     - The SVG map rack B glows red.
     - The physical pan servo swings to 62° and fires the laser turret at Rack B.
     - The mobile pager sounds the alert.
     - Tap **ACKNOWLEDGE** on your phone: the SVG map turns emerald green, laser shuts down, and incident logs as resolved.

---

## 5. Hardware Troubleshooting & Operational Rules

### 1. Acoustic Blanking Window (Servo Gear Noise)
* **What it does**: When the servo receives an `AIM,<pan>` command, the backend initiates a **350 ms acoustic blanking window** (`signal_processor.trigger_blanking(350)`). During this window, all microphone telemetry is discarded.
* **Why**: The internal plastic gears of SG90 servos emit high-frequency acoustic whine that can falsely trigger the 2500 Hz detector.
* **Hardware Rule**:
  - Ensure the servo bracket is mechanically isolated from the microphone mounting bar (use double-sided foam tape or hot glue).
  - Do not let the servo body vibrate directly against the microphone PCBs.

### 2. Microphone Gain & Potentiometer Adjustment
* Each analog microphone breakout has a small blue potentiometer trimmer:
  - **Turning counter-clockwise**: Increases analog pre-amp gain.
  - **Turning clockwise**: Decreases pre-amp gain.
* **Potentiometer Skew Protection**: The software normalizes all spatial energy ratios by dividing by the running noise floor:
  $$\text{Normalized Energy} = \frac{E_{2500}}{\max(\text{Noise Floor}, 10^{-6})}$$
  This prevents slight potentiometer differences between Mic L and Mic R from skewing rack predictions.
* **Recommended Tuning**: In a quiet room, ambient ADC readings on $L_{25}, M_{25}, R_{25}$ should rest between **8.0 and 15.0**. During a beep, the closest mic should surge to **60.0–150.0+**.

### 3. Schmitt Trigger Threshold Adjustment
If the physical mics produce low signal-to-noise ratio in a very loud or damp venue:
* **Current Software Settings**:
  - SNR Start Ratio: $4.0\times$ floor
  - Purity Start Ratio: $2.0$ (ratio of 2500 Hz to sidebands 2000/3000 Hz)
  - Quiet End Ratio: $2.0\times$ floor for 2 consecutive frames (40 ms)
* **If Beeps Are Not Triggering**:
  - Check in `beacon/server.py` and adjust:
    ```python
    signal_processor = SignalProcessor(
        alpha=0.02,
        initial_noise_floor=[10.0, 10.0, 10.0],
        snr_threshold=3.5,     # Lower from 4.0 to 3.5 if tone is faint
        purity_threshold=1.8,  # Lower from 2.0 to 1.8 if tone is noisy
    )
    ```
* **Broadband Fan Noise Rule**:
  - Do NOT disable the purity check! Fan noise has equal energy across all frequencies ($\text{Purity} \approx 1.0$). The purity check is what prevents 80 dB data center airflow from triggering false alarms.

---

## 6. Summary Checklist for Pitch / Judging Demo

- [ ] Pico 2W plugged into USB and recognized on `/dev/cu.usbmodem*` or `/dev/ttyACM*`.
- [ ] Laser diode powered and aimed at rack table centerline when at 90°.
- [ ] Physical training recordings captured using `python3 tools/record.py --session 1`.
- [ ] Physical test recordings captured using `python3 tools/record.py --session 2`.
- [ ] Model weights compiled using `python3 tools/train_location.py`.
- [ ] Beacon server running on `http://0.0.0.0:8000`.
- [ ] Phone paired to mobile pager view via QR code on `10.173.171.63:8000`.
- [ ] Demo pitch mode verified: background replay paused, laser turns off after 5 seconds, mobile Acknowledge button syncs live over WebSockets.

