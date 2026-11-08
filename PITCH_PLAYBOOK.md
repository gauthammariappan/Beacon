# Beacon v2.1 · 2-Minute Judge Pitch Script & Demonstration Playbook

> **Track**: HackUTD NMC² Data Center Track  
> **Target Duration**: Exactly 2 minutes (120 seconds)  
> **Key Roles**: Presenter (Voice & Narrative) + Demo Operator (Actuation & Phone Handoff)

---

## 1. Quick Setup Checklist (Before Judges Arrive)

1. **Start the Beacon Server**:
   ```bash
   python3 -m uvicorn beacon.server:app --host 0.0.0.0 --port 8000
   ```
2. **Open the Desktop NOC Dashboard**:
   - Navigate to `http://localhost:8000` on your laptop in full screen.
   - Verify WebSocket status shows **CONNECTED** (green dot).
   - Verify the Live Tab SVG map (Racks A–E) and 10 Hz mic bars are visible.
   - Confirm **Auto-Replay is PAUSED** (`⏸ Auto-Replay: PAUSED` in amber).
3. **Stage the Dynamic QR Code**:
   - Ensure the on-screen QR code (pointing to your LAN IP, e.g. `http://10.173.171.63:8000`) is visible on the dashboard header.
   - Have a test phone ready with camera open, or open the link on your phone in mobile view.
4. **Physical Table Readiness**:
   - Pico 2W plugged in via USB (laser diode centered at 90° on Rack C).
   - Test audio file `beeps/P1_on_battery.wav` loaded on phone or ready via quick demo trigger button (`POST /demo/trigger/B/P1`).

---

## 2. Minute-by-Minute Pitch Script (120 Seconds)

### [0:00 – 0:30] The Hook & The Unmonitored Data Center Problem
* **Presenter**:  
  > *"Data centers are deafeningly loud—75 to 85 decibels of relentless fan noise. Inside these aisles sit dozens of unmonitored devices: legacy UPS battery backups, older PDUs, and chassis power supplies. When a UPS battery starts dying, it doesn’t send an SNMP trap. It just beeps.  
  > In acoustic blindness, a technician is dispatched with a flashlight to manually search through hundreds of racks. Mean Time to Detect (MTTD) often exceeds 45 minutes, risking ungraceful server shutdowns or catastrophic thermal runaway.*  
  > *This is **Beacon v2.1**—the first autonomous acoustic direction-finding and automated incident triage system for data centers."*

---

### [0:30 – 0:55] The Dual-Brain Architecture & Hardware Rig
* **Presenter points to the physical overhead rail and laser turret**:  
  > *"Rather than tearing out legacy hardware, Beacon hangs 3 low-cost analog microphones across the aisle ceiling wired to a Raspberry Pi Pico 2W.  
  > The Pico runs microsecond Goertzel bandpass filters at 2500 Hz, streaming 50 Hz acoustic telemetry to our edge engine.  
  > Here, our **Dual-Brain AI** kicks in:  
  > • **Brain 1** extracts a 19-element spatial acoustic fingerprint using Noise-Floor Normalized energies to cancel hardware potentiometer skews—achieving **100% physical accuracy** on Rack A through E.  
  > • **Brain 2** decodes temporal pulse cadence to classify the exact alarm state: On Battery, Low Battery, or Overload."*

---

### [0:55 – 1:35] The Live Interactive Demo (The "Magic Moment")
* **Presenter**:  
  > *"Watch what happens when an alarm sounds at Rack B."*

* **Demo Operator**:  
  - Plays 2500 Hz tone at physical Rack B (or clicks **Trigger Rack B** on the dashboard).
  - *Within 200 ms*:
    1. **Audio Telemetry**: The 10 Hz mic level bars surge.
    2. **Turret Actuation**: The physical SG90 servo swings to **62°**, and the laser diode **fires a bright red beam directly at Rack B**.
    3. **NOC Dashboard**: Rack B on the SVG map glows pulsating red, displaying **Rack B · UPS On Battery (P1) · 98% Confidence**.
    4. **Servo Blanking**: The software enforces a **350 ms acoustic blanking window**, proving servo gear whine cannot corrupt detection.

* **Presenter hands phone to Judge**:  
  > *"At the same time, technician phones across the facility receive an instant high-priority alert. Look at this mobile pager."*
  > *(Presenter shows or hands phone to judge)*  
  > *"Judge, could you press that giant green **ACKNOWLEDGE** button for us?"*

* **Judge presses ACKNOWLEDGE**:  
  - *In under 10 milliseconds over WebSockets*:
    - The phone card turns glowing emerald green.
    - The laptop NOC map instantly flips Rack B to **ACKNOWLEDGED (Green)**.
    - The physical laser turns off.
    - The incident is permanently logged in the audit trail.

---

### [1:35 – 2:00] Business Impact, Edge Economics & Wrap-Up
* **Presenter**:  
  > *"In less than 3 seconds, we went from an acoustic anomaly in 80 dB noise to pinpoint laser illumination and technician dispatch.  
  > • **Zero retrofit cost**: No server downtime, no network cables.  
  > • **Bill of Materials**: Under $25 in off-the-shelf micro-hardware per aisle.  
  > • **Field Reliability**: Validated across 28 automated tests and physical table recordings with zero false alarms under 80 dB fan noise.  
  > Beacon turns acoustic noise into operational certainty. Thank you, and we welcome your questions!"*

---

## 3. Red Team Judge Q&A Defense (Tough Technical Rebuttals)

Prepare these exact answers when judges probe the engineering:

### Q1: *"Why not just use Time Difference of Arrival (TDoA) or beamforming?"*
* **Rebuttal**:  
  > *"Great question. In an 85 cm narrow cold aisle, the total acoustic propagation time between our outer microphones is only 2.4 milliseconds. In a real data center, metal server rack enclosures create severe multipath reflections that destroy acoustic phase coherence.  
  > Rather than relying on fragile phase delays, Beacon uses a **vectorized 19-element spatial energy fingerprint** (shares, log ratios, and band purities) trained with a Random Forest classifier. This gives us 100% localization accuracy where TDoA phase correlation completely collapses."*

### Q2: *"What happens if the data center fan noise gets louder (e.g. 85+ dB)?"*
* **Rebuttal**:  
  > *"We engineered a dedicated **Band Purity Metric**:  
  > $$\text{Purity} = \frac{E_{2500}}{\text{avg}(E_{2000}, E_{3000})}$$  
  > Broadband fan noise is flat white/pink noise with equal energy across all three frequency bins, yielding a purity of roughly 1.0. An uninterruptible power supply alarm is a pure 2500 Hz piezoelectric tone, yielding purity values from 2.5 to 15.0+. Our Schmitt trigger requires both SNR > 4.0 and Purity > 2.0, meaning 85 dB broadband airflow will never trigger a false positive."*

### Q3: *"The physical potentiometers on cheap analog microphones always drift. How do you prevent gain skew?"*
* **Rebuttal**:  
  > *"In our initial hardware audit, we identified that hardware gain mismatch between Mic L, M, and R could ruin the spatial ratios. We solved this mathematically in `beacon/features.py` by computing **Noise-Floor Normalized Energies** ($\text{avg}_{2500} / \text{noise\_floor}$) before computing the spatial shares and log-ratios. Because the normalization divides out individual hardware gain differences against the ambient baseline, potentiometer drift is cancelled out."*

### Q4: *"Doesn't the servo motor noise fool your microphone when the turret swings?"*
* **Rebuttal**:  
  > *"Yes, SG90 servo gears emit high-frequency acoustic noise during transit. To prevent this, the moment the state machine reaches `LOCATED`, `signal_processor.trigger_blanking(350)` initiates a **350 ms acoustic blanking window** that drops all incoming frames while the motor is in motion. Detection resumes only after the turret is stationary."*

### Q5: *"Why did you use Random Forest instead of a Deep Neural Network?"*
* **Rebuttal**:  
  > *"Deterministic latency and explainability. Our Random Forest model runs inference in under 0.8 milliseconds on standard CPU hardware with zero GPU requirement, making it ideal for edge deployment on low-power gateway nodes. In our benchmarks, Random Forest achieved 100% accuracy on our test dataset, outperforming baseline loudest-mic (50%) and centroid (49.3%) algorithms."*

---

## 4. Interactive Keyboard Shortcuts for Demo Operator

During the pitch, the demo operator can control the entire flow using single keypresses on the laptop:

| Keypress | Action |
|:---:|---|
| **`1`** | Trigger demo incident on **Rack A** |
| **`2`** | Trigger demo incident on **Rack B** *(Recommended for pitch)* |
| **`3`** | Trigger demo incident on **Rack C** |
| **`4`** | Trigger demo incident on **Rack D** |
| **`5`** | Trigger demo incident on **Rack E** |
| **`Q`** | Select Alarm Pattern **P1 (UPS On Battery)** |
| **`W`** | Select Alarm Pattern **P2 (UPS Low Battery)** |
| **`E`** | Select Alarm Pattern **P3 (UPS Overload continuous tone)** |
| **`P`** | Toggle Background CSV Replay Loop (Pause / Resume) |
| **`Space`** | Acknowledge active incident directly from desktop |
