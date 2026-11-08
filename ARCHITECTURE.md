# Beacon: Final Architecture (v2.1)

> v2.1 changes: no header strip needed (long mic wires are chained M-F + F-F), laser turret is pan-only by default (tilt is optional), updated wire budget.

Acoustic localization for unmonitored data center equipment. Built for the NMC² track at HackUTD.

---

## 1. What it is

**The problem.** A data hall sits at 70–80+ dB of fan noise. When an unmonitored UPS or PDU starts beeping, the beep gets buried in that noise and bounces off every rack, so nobody can tell which rack it's coming from or what the alarm means. Techs end up walking the aisles hunting for it.

**Beacon.** Three mics hung over the aisle cover a row of five racks. Nothing gets attached to the racks and nothing is connected to the beeping devices. Beacon:

1. **Hears** the beep under the fan noise
2. **Locates** the rack with an ML model trained on the aisle's acoustic fingerprint
3. **Identifies** the alarm from its beep pattern
4. **Points** a laser at the rack, lights it up on the dashboard, and **sends an alert** to a phone

> "A few sensors per row, zero integration. If it beeps, we find it."

---

## 2. Physical layout

```
   ┌─────┐  ┌─────┐  ┌─────┐  ┌─────┐  ┌─────┐
   │  A  │  │  B  │  │  C  │  │  D  │  │  E  │   5 boxes, ~15 cm wide,
   └──▽──┘  └──▽──┘  └──▽──┘  └──▽──┘  └──▽──┘   ~3 cm gaps, openings face aisle
 ═══════════════════ AISLE (~85 cm) ═══════════════
      🎤L                🎤M                🎤R    mics on cardboard arms ~15 cm up,
   in front of A     in front of C     in front of E

                 [Pico]  ← next to mic M, center of the aisle
                    │ USB
          [Laser turret] ~40 cm back from the racks, centered
                    │
                [Laptop]  screen faces the judges
```

- **Mics sit in front of A, C and E.** Racks B and D are *between* two mics, so "loudest mic wins" can never name them. That gives the ML model a real job: learning the ratios between mics.
- **Beeper:** a phone playing a generated 2500 Hz beep-pattern WAV. The judge drops it in any rack.
- **Fan noise:** a second phone playing data center noise.
- **Laser turret is pan-only.** The laser is glued to one servo arm, angled slightly down at a fixed angle so the beam lands on the box fronts. Swinging left/right is enough to hit any of the 5 racks in a row. A tilt servo is an optional upgrade.
- **Tape everything down.** If a mic moves after training, accuracy drops.

---

## 3. Parts

### Checked out from HackUTD

Return everything after judging to get the license back.

| Part | Qty | Role |
|---|---|---|
| Raspberry Pi Pico 2 WH | 1 | The only microcontroller. Reads mics, drives servos + laser, talks to the laptop |
| **Small Sound** (mic module) | **3** | Mics L, M, R |
| SG90 Micro Servo | 3 | Pan (1 used), tilt is optional, the rest are spares |
| Laser Emit | 2 | Pointer, 1 spare |
| NPN Transistor PN2222 | 1 | Switches the laser on and off |
| Resistor | 1 | **Must be 1k** (brown-black-red). Sits between the Pico pin and the transistor base |
| 100µF Electrolytic Capacitor | 2 | Steadies servo power, 1 spare |
| Power Supply Module | 1 | Turns the 9 V battery pack into 5 V. **Set the jumper to 5V** |
| 6xAA Battery Holder w/ Switch | 1 | Powers the servos and laser |
| Diode 1N4007 | 1 | Spare, not used in this design |
| Jumper Wires F-F | 22 | Mics, laser circuit, ground link |
| Jumper Wires M-F | 8 | Servo plug + extensions for the far mics |
| Super Glue | 1 | Turret assembly |

### Still to get

| Part | Qty | Why |
|---|---|---|
| **Jumper Wires M-F** | **2** | We need 9 and have 8 (4 more if we add the tilt servo) |
| *Only if the mic test fails at 40 cm:* PN2222 ×3, 10k/100k/1k resistors, 10µF ×3 | — | Mic preamps |

Nothing else is needed to start. The mic test, servo test and laser test all use parts we already have.

### From home

| Item | Why |
|---|---|
| Micro-USB data cable | Flashing the Pico, power, serial to the laptop |
| Laptop | Runs all the software and the dashboard |
| 6 AA batteries | Battery pack |
| 5 boxes, tape, scissors | Racks, mic arms, mounting |
| 2 phones | Beeper + fan noise |
| Pi 5 kit | Backup only. The laptop is the hub |

---

## 4. Wiring

### Pin map

| Connection | Goes to |
|---|---|
| Mic L **AO** / M **AO** / R **AO** | **GP26 / GP27 / GP28** (the 3 analog inputs) |
| Mic L **+** / M **+** / R **+** | **GP2 / GP3 / GP4**, set HIGH in code to give 3.3 V (no breadboard needed) |
| Mic **G** ×3 | Pico GND pins (use pin 33, the analog ground, for mic M) |
| Mic **DO** | Not used |
| Pan servo orange (signal) | **GP15** |
| Tilt servo orange (signal), optional | **GP14** |
| Servo red / brown | Power module **5V / GND** |
| Laser **S** (+) | Power module **5V** |
| Laser **−** | PN2222 **collector** (right leg, flat side facing you) |
| PN2222 **emitter** (left leg) | **Pico GND** |
| **GP13** → 1k resistor → | PN2222 **base** (middle leg) |
| 100µF capacitor (long leg = +) | Across power module 5V and GND |
| Power module GND → Pico GND | **One** wire. Required, all grounds must be shared |
| Battery pack | Power module input |
| Pico | USB to the laptop (power + data) |

### Wire budget

| Run | Wires |
|---|---|
| Mic M (next to the Pico) | 3 F-F |
| Mics L and R, ~40 cm each. Each wire is an F-F on the Pico pin, with the male end of an M-F pushed into its other end, and the M-F's female end on the mic pin | 6 F-F + 6 M-F |
| Laser circuit | 5 F-F (resistor and transistor legs push into the jumper ends) |
| Capacitor | 2 F-F |
| Ground link | 1 F-F |
| Pan servo (its plug is female, so M-F wires plug into it) | 3 M-F |
| **Total** | **17 F-F (have 22), 9 M-F (have 8, get 2)** |
| *Optional tilt servo* | *+3 M-F* |

### Two checks before wiring power

1. **Battery to power module.** The module input is usually a barrel jack and the battery holder has bare wires. Ask the help desk for a barrel adapter. Fallback: power the servos and laser from the Pico's **VBUS** pin (USB 5 V) with the capacitor attached, and move the servos slowly.
2. **Power module pin count.** With pan-only, 5V needs 3 connections (servo, laser, capacitor) and GND needs 3 (servo, capacitor, ground link). If we run out of pins, twist the wires together and tape them.

---

## 5. Software: seven layers

```
┌──────────────────────────────────────────────────────────────┐
│ 7  PRESENTATION  Dashboard (Live·Model·Setup) · Phone page    │ browser
│ 6  API           FastAPI + WebSocket                          │
│ 5  ACTION        Incident manager · Aim controller · Notifier │
│ 4  INFERENCE     ML location model · Pattern decoder          │ laptop
│ 3  SIGNAL        Noise floor · Purity · Beep detector · Feats │ (Python)
│ 2  INGEST        Serial bridge · Recorder · Replay simulator  │
╞══════════════════════════════════════════════════════════════╡
│ 1  SENSING       3 mics → burst sample → Goertzel ×3 freqs    │ Pico
└──────────────────────────────────────────────────────────────┘
```

### One beep, end to end

```
0 ms      Phone in Rack B beeps at 2500 Hz → L loud, M medium, R quiet
20 ms     Pico: 16 ms burst → Goertzel at 2000/2500/3000 Hz → one serial line
60 ms     Signal: L > 5× floor + high purity → BEEP START (floor freezes)
300 ms    Signal: all < 2× floor for 2 frames → BEEP END → 19 features
305 ms    Model → {A .05, B .89, C .04, D .01, E .00, NONE .01}
310 ms    Action: incident "Rack B 89%" → AIM + LASER on → 350 ms blanking
350 ms    Screens: B glows, phone shows "Rack B · identifying alarm…"
2–5 s     Pattern decoder → "UPS: on battery" → screens update
```

Location shows up after one beep. The alarm type needs a few beeps, since you can't recognize a rhythm from a single beat. The screens show "identifying alarm…" until the pattern locks in.

### Layer 1: Sensing (Pico, Arduino IDE + arduino-pico core)

- Every 20 ms, capture **256 samples per mic at 16 kHz** with precise timing (one round of all 3 mics every 62.5 µs). Even spacing between samples keeps the filter locked on the right frequency.
- Run **Goertzel** on each mic at **2500 Hz** (the beep) and **2000 / 3000 Hz** (reference bands). At 16 kHz and 256 samples, all three land exactly on filter bins 32, 40 and 48.
- After the burst, send one line:
  `E,<ms>,L25,M25,R25,L20,M20,R20,L30,M30,R30`
- Listen for commands from the laptop:
  - `AIM,<pan>` (or `AIM,<pan>,<tilt>` if the tilt servo is added): move smoothly, always approaching from the same side to cancel gear slop
  - `LASER,1` / `LASER,0`
- **The Pico makes no decisions.** It's a sensor and a motor driver. All the thinking happens on the laptop.

### Layer 2: Ingest (Python)

| Component | What it does |
|---|---|
| Serial bridge | `pyserial`, both directions |
| Recorder | Saves every frame to CSV with a label and session number. **This is the training data** |
| Replay simulator | Plays a CSV back as if it were live (`--replay file.csv`). **Software teammates can build layers 3–7 without hardware** |

### Layer 3: Signal processing

1. **Noise floor** per mic: slow rolling average of the 2500 Hz energy. **Freezes while a beep is active**, so a long steady tone (the overload alarm) doesn't get absorbed into the background.
2. **Purity** = E2500 ÷ average(E2000, E3000). A beep is high. Claps, speech and table bumps are close to 1.
3. **Beep detector with hysteresis**
   - Start: any mic above 5× its floor **and** purity is high
   - End: every mic below 2× its floor for 2 frames in a row
4. **Blanking:** ignore all input for 350 ms after every `AIM`, so servo noise doesn't count as a beep.
5. **Features per beep (19 total)**

| Feature | Count | Why |
|---|---|---|
| Average 2500 Hz energy per mic | 3 | How loud each mic heard it |
| Share of total per mic | 3 | Works no matter how loud the phone is |
| Log ratios (L/M, M/R, L/R) | 3 | The core fingerprint |
| Peak energy per mic | 3 | Short, sharp beeps |
| SNR per mic | 3 | How much to trust each reading |
| Purity per mic | 3 | Tone vs. noise, helps reject false triggers |
| Duration | 1 | Used by the pattern decoder |

### Layer 4: Inference

Two brains. ML where the problem is fuzzy (room acoustics), rules where the answer is defined (manufacturer beep codes).

#### Location (machine learning)

| Method | What it does | Role |
|---|---|---|
| Loudest mic | Picks A, C or E | Baseline 1. Can't name B or D at all |
| Weighted centroid | Estimates a position from each mic's share of the loudness, snaps to the nearest rack | Baseline 2. The fair non-ML comparison |
| **Random forest** (try kNN too) | Learns this aisle's fingerprint, including echoes and leakage | **The model. Has to beat both baselines** |

- **Classes:** A, B, C, D, E, NONE
- **Training data:** ~40 beeps per rack plus ~40 NONE (claps, talking, fan noise only), recorded in **2 separate sessions**. Vary the phone's angle and volume on purpose so the model learns the rack, not how the phone happened to sit.
- **Evaluation:** train on session 1, test on session 2. Report accuracy and a confusion matrix for all 3 methods. Only quote numbers we actually measured.
- **Uncertainty:** top probability under 0.6 → "between B and C". NONE → discard the event.
- **Smoothing:** location is a running vote across beeps, so confidence climbs with every beep.
- **Rule:** never touch the mics' sensitivity knobs after training.

#### Alarm type (rule-based pattern decoder)

Matches beep on/off timing against `patterns.json`. Patterns are based on APC's documented alarms ([APC FAQ](https://www.se.com/us/en/faqs/FA156554/)), with timing shortened for the demo:

| Pattern | Sound | Meaning | Action |
|---|---|---|---|
| P1 | 4 short beeps, then a pause (really every 30 s, ~5 s in the demo) | UPS on battery | Check upstream power / generator |
| P2 | Continuous rapid beeping | UPS low battery | Shed load or start a graceful shutdown |
| P3 | Steady tone | UPS overload | Reduce load |

### Layer 5: Action

- **Incident manager**
  - States: `DETECTED → LOCATED → IDENTIFIED → ACKNOWLEDGED → CLEARED`
  - Many beeps from one rack become one incident, which clears after 10 s of silence
  - Keeps a history
- **Aim controller**
  - Looks up the rack's angles in `aim_points.json`, sends `AIM` + `LASER,1`, starts the blanking window
  - Turns the laser off after 5 s
  - Only re-aims if the vote changes racks
- **Notifier:** pushes every incident change to the API

### Layer 6: API (FastAPI)

| Endpoint | Purpose |
|---|---|
| `WS /live` | Mic levels (10 per second), events, incidents |
| `GET /layout` | Rack and mic positions |
| `GET /incidents` | History |
| `POST /incidents/{id}/ack` | Phone's Acknowledge button |
| `GET /model/metrics` | Results for all 3 methods |
| `POST /laser/jog`, `POST /calibrate/aim/{rack}` | Laser setup |
| `GET /`, `GET /alert` | Dashboard and phone page |

### Layer 7: Presentation

- **Live tab:** top-down map with the predicted rack glowing, a live bar and purity dot per mic, the incident card ("Rack B · 89% · 12-beep vote · UPS on battery"), and an event log.
- **Model tab:** accuracy for all three methods side by side, confusion matrices, feature importances. This is the "why ML" proof for judges.
- **Setup tab:** arrow-key laser aiming with a save button per rack, noise floor view, record-session button.
- **Phone page:** opened from a QR code. Big alert card plus **Acknowledge**, which updates the dashboard live. Run everything on a **phone hotspot**, since venue Wi-Fi often blocks phone-to-laptop traffic.

---

## 6. Data contracts

Agree on these first so everyone can build in parallel.

```text
Pico → laptop   E,<ms>,L25,M25,R25,L20,M20,R20,L30,M30,R30
Laptop → Pico   AIM,<pan>[,<tilt>]  |  LASER,1  |  LASER,0
```

Beep event (layer 3 → 4):

```json
{"id":"ev_812","t_start":12.10,"t_end":12.30,
 "features":{"share":[0.58,0.38,0.04],"log_ratio":[0.41,2.2,2.6],
   "peak":[0.74,0.51,0.07],"snr_db":[18.2,14.9,2.1],
   "purity":[9.8,8.7,1.3],"dur_ms":200}}
```

Incident (layer 5 → 6 → 7):

```json
{"id":"inc_17","state":"IDENTIFIED","rack":"B","confidence":0.89,
 "runner_up":{"rack":"A","p":0.06},"beeps":12,
 "alarm":{"device":"UPS","meaning":"On battery","action":"Check upstream power","pattern":"P1"},
 "first_heard":"02:13:07"}
```

### Files

| File | Contents |
|---|---|
| `rack_layout.json` | Rack and mic positions |
| `aim_points.json` | Laser pan angle (and tilt, if used) per rack |
| `patterns.json` | Alarm library |
| `recordings/session{1,2}_*.csv` | Training data |
| `model.joblib` | Trained model |
| `metrics.json` | Test results |
| `beeps/*.wav` | Beep sounds for the phone |

### Tech stack

- **Firmware:** Arduino IDE + arduino-pico core
- **Backend:** Python 3, `pyserial`, `numpy`, `scikit-learn`, `joblib`, `FastAPI`, `uvicorn`
- **Frontend:** HTML/JS or React (Vite), SVG map
- **SpacetimeDB:** skipped, unless their sponsors confirm a Python-heavy backend still qualifies

---

## 7. Tasks

| Stream | In order |
|---|---|
| **A: Hardware** | **A1 mic test at 40 cm (do this first)** → A2 burst sampling + 3-frequency Goertzel → A3 all 3 mics streaming → A4 glue the laser to the pan servo and wire it → A5 `AIM` / `LASER` working → A6 5 boxes + mic arms, all taped down |
| **B: Data + ML** | B1 beep WAV generator → B2 recorder → B3 signal layer → **B4 record sessions 1 and 2 (~45 min)** → B5 both baselines → B6 random forest / kNN, test on session 2 → B7 uncertainty threshold → B8 pattern decoder |
| **C: Backend** | C1 serial + replay → C2 full pipeline on replay data → C3 incident manager → C4 aim + blanking → C5 FastAPI + WebSocket → C6 calibration endpoints |
| **D: Frontend + pitch** | D1 Live tab on replay data → D2 phone page + QR → D3 Model tab → D4 Setup tab → D5 2-minute pitch |
| **E: Everyone** | E1 full live run → E2 hotspot test with a stranger's phone → **E3 20 runs, write down the hit rate** → E4 screen-record a perfect run as backup |

**Critical path:** mic test → boxes and arms → data collection → model. Everything else can run in parallel on replay data.

### Mic test (A1) quick steps

1. Install the Arduino IDE. In Preferences → Additional boards manager URLs, add:
   `https://github.com/earlephilhower/arduino-pico/releases/download/global/package_rp2040_index.json`
2. Boards Manager → install **Raspberry Pi Pico/RP2040/RP2350** → select **Raspberry Pi Pico 2W**.
3. Wire one mic: **AO → GP26, + → GP2, G → GND**.
4. Flash a sketch that sets GP2 HIGH and prints GP26 readings fast. Open the Serial Plotter.
5. Play a 2500 Hz tone from a phone, first close, then at ~40 cm.
   - Waveform clearly grows at 40 cm → good, go build
   - Only grows when the phone is touching the mic → too weak, get preamp parts or move mics closer
   - Stuck at 0 or 4095 → check wiring

---

## 8. Top risks

| Risk | Plan |
|---|---|
| Mics too weak at 40 cm | Phone volume all the way up → mic preamps → shorter arms closer to the racks |
| Can't connect the battery to the power module | Power from VBUS with the capacitor, move servos slowly |
| Servo noise or brownouts | 350 ms blanking, shared ground, capacitor |
| Phone can't reach the laptop | Phone hotspot |
| Model doesn't beat the centroid baseline | Show it honestly. "3 sensors localize 5 racks" is still the story, and more training data is the next step |

---

## 9. Judge Q&A cheat sheet

| Question | Answer |
|---|---|
| "Why ML?" | Show the Model tab. Loudest-mic can't name B or D at all, the centroid is the best non-ML method, and the model beats both (with our measured numbers). |
| "Is it really zero integration?" | 3 sensors cover a row of 5 racks. Nothing is attached to the racks or connected to the devices. |
| "What if the room changes?" | Recalibration is one walk down the row with a beeper, about 10 minutes per row. |
| "Why not just use SNMP?" | These devices don't have it. That's exactly why they beep. |
| "Why rules for the alarm type?" | Beep codes are defined by the manufacturers. ML goes where the problem is fuzzy, which is the room's acoustics. |
