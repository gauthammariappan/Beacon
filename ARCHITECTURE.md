# Beacon: Final Architecture (v3.0, scripted locator)

> **v3.0 changes**
> - **Which rack is beeping is now scripted** (operator hotkey), not predicted by an ML model. The ML locator is documented in Appendix A as the designed next step. It is **not built**, and we say so.
> - Everything downstream of "which rack" is real: turret control, incident flow, dashboard, phone alert.
> - Mics and beep detection are an **optional tier** (Tier 1), not on the critical path.
> - The dashboard shows a **SCRIPTED** badge on every incident and no confidence percentages, so the screen never claims more than we built.
> - New turret firmware: eased motion, always approaches each target from the same side, lock-on blink, laser failsafe.

Acoustic localization concept for unmonitored data center equipment. Built for the NMC² track at HackUTD.

---

## 1. What it is, and what is real

**The problem.** A data hall sits at 70-80+ dB of fan noise. When an unmonitored UPS or PDU starts beeping, the beep is buried in noise and bounces off every rack, so nobody can tell which rack it's coming from or what the alarm means. Techs end up walking the aisles hunting for it.

**Beacon.** A small sensor set over the aisle, nothing attached to the racks, nothing connected to the beeping devices. Beacon (1) hears the beep, (2) works out which rack, (3) identifies the alarm from its beep pattern, (4) points a laser at the rack, lights it up on the dashboard, and alerts a phone.

> "A few sensors per row, zero integration. If it beeps, we find it."

### Honest status (use this table in the pitch)

| Piece | Status |
|---|---|
| Laser turret: eased pan, calibrated per-rack angles, lock-on, failsafe | **Real, built, measured** |
| Incident flow, dashboard, phone alert with Acknowledge | **Real, built** |
| Alarm meaning and recommended action | **One hardcoded alarm** (UPS on battery), shown as a lookup |
| Which rack is beeping | **Scripted** (operator hotkey) |
| Beep detection from mics | **Tier 1, only if time allows** |
| ML rack locator | **Designed, not built** (Appendix A) |

---

## 2. Physical layout

```
   ┌─────┐  ┌─────┐  ┌─────┐  ┌─────┐  ┌─────┐
   │  A  │  │  B  │  │  C  │  │  D  │  │  E  │   5 boxes, ~15 cm wide,
   └──▽──┘  └──▽──┘  └──▽──┘  └──▽──┘  └──▽──┘   ~3 cm gaps, openings face aisle
 ═══════════════════ AISLE (~85 cm) ═══════════════
      🎤L                🎤M                🎤R    Tier 1 only: mics ~15 cm up
                 [Pico]
                    │ USB
          [Laser turret] ~40 cm back from the racks, centered
                    │
                [Laptop]  screen faces the judges
```

- **Beeper:** a phone playing a generated 2500 Hz beep-pattern WAV, dropped in any rack. For realism the phone beeps in the rack the operator selects.
- **Fan noise:** a second phone playing data center noise.
- **Turret is pan-only.** The laser is glued to the servo arm at a fixed downward angle so the beam lands on the box fronts. Swinging left/right reaches all 5 racks. A tilt servo is an optional upgrade.
- **Tape everything down.** If the turret or a box moves after calibration, the dot misses. Recalibrate (Section 9) after anything moves.
- **Laser safety:** fixed downward tilt, never aimed at people, firmware auto-off after 10 s. Tell judges to stay out of the beam path.

---

## 3. Parts

### Checked out from HackUTD (return everything after judging)

| Part | Qty | Tier | Role |
|---|---|---|---|
| Raspberry Pi Pico 2 WH | 1 | 0 | Drives servo + laser, talks to the laptop |
| SG90 Micro Servo | 3 | 0 | Pan (1 used), rest are spares |
| Laser Emit | 2 | 0 | Pointer, 1 spare |
| NPN Transistor PN2222 | 1 | 0 | Switches the laser |
| Resistor | 1 | 0 | **Must be 1k** (brown-black-red), between the Pico pin and the transistor base |
| 100µF Electrolytic Capacitor | 2 | 0 | Steadies servo power, 1 spare |
| Power Supply Module | 1 | 0 | 9 V pack to 5 V. **Set the jumper to 5V** |
| 6xAA Battery Holder w/ Switch | 1 | 0 | Powers servo + laser |
| Jumper Wires F-F | 22 | 0 / 1 | See wire budget |
| Jumper Wires M-F | 8 | 0 / 1 | Servo plug (Tier 0), far-mic extensions (Tier 1) |
| Super Glue | 1 | 0 | Turret assembly |
| **Small Sound** (mic module) | 3 | **1** | Optional mics L, M, R |
| Diode 1N4007 | 1 | - | Spare, unused |

### Still to get

| Part | Qty | Why |
|---|---|---|
| Jumper Wires M-F | 2 | **Tier 1 only** (far mics need 9, we have 8). Tier 0 needs 3 |

### From home

Micro-USB data cable, laptop, 6 AA batteries, 5 boxes + tape + scissors, 2 phones. Pi 5 kit is backup only.

---

## 4. Wiring

### Pin map

| Connection | Goes to |
|---|---|
| Pan servo orange (signal) | **GP15** |
| Servo red / brown | Power module **5V / GND** |
| Laser **S** (+) | Power module **5V** |
| Laser **−** | PN2222 **collector** (right leg, flat side facing you) |
| PN2222 **emitter** (left leg) | **Pico GND** |
| **GP13** → 1k resistor → | PN2222 **base** (middle leg) |
| 100µF capacitor (long leg = +) | Across power module 5V and GND |
| Power module GND → Pico GND | **One** wire. Required, all grounds must be shared |
| Battery pack | Power module input |
| Pico | USB to the laptop (power + data) |
| *Tier 1:* Mic L / M / R **AO** | GP26 / GP27 / GP28 |
| *Tier 1:* Mic L / M / R **+** | GP2 / GP3 / GP4, set HIGH in code |
| *Tier 1:* Mic **G** ×3 | Pico GND (pin 33, analog ground, for mic M) |

### Wire budget

| Run | F-F | M-F |
|---|---|---|
| **Tier 0:** laser circuit (resistor and transistor legs push into jumper ends) | 5 | |
| **Tier 0:** capacitor | 2 | |
| **Tier 0:** ground link | 1 | |
| **Tier 0:** pan servo (its plug is female) | | 3 |
| **Tier 0 total** | **8 (have 22)** | **3 (have 8)** |
| Tier 1: mic M next to the Pico | 3 | |
| Tier 1: mics L and R, ~40 cm each (F-F on the Pico pin, M-F pushed into its other end, female end on the mic pin) | 6 | 6 |
| **Tier 1 total** | **17** | **9 (get 2)** |

### Two checks before wiring power

1. **Battery to power module.** The module input is usually a barrel jack and the battery holder has bare wires. Ask the help desk for a barrel adapter. Fallback: power servo and laser from the Pico's **VBUS** pin (USB 5 V) with the capacitor attached. The glide motion in the firmware keeps current spikes small.
2. **Power module pin count.** 5V needs 3 connections (servo, laser, capacitor) and GND needs 3 (servo, capacitor, ground link). If you run out of pins, twist wires together and tape.

---

## 5. Software

### Tiers

| Tier | What | Why it's separate |
|---|---|---|
| **0 (the demo)** | Scripted trigger → turret + dashboard + phone | Everything on the critical path is built and tested |
| 1 | Real beep detection from mics (Goertzel, purity, hysteresis) | "Hears" becomes real. Rack is still scripted. Armed mode: operator arms a rack and the first real beep fires it |
| 2 | Hand-tuned rule locator (loudest mic, snap between mics) | Non-ML, ~20 lines, thresholds tuned from ~5 beeps per rack |
| 3 | ML locator | Designed, not built (Appendix A) |

### Layers

```
┌──────────────────────────────────────────────────────────────────┐
│ 5  PRESENTATION  Dashboard (Live · Setup · Approach) · Phone page  │ browser
│ 4  API           FastAPI + WebSocket                               │
│ 3  ACTION        Incident manager · Aim controller · Notifier      │ laptop
│ 2  LOCATOR       locate() ← the swap point (scripted today)        │ (Python)
│ 1  INGEST        Serial bridge (+ recorder/replay for Tier 1+)     │
╞══════════════════════════════════════════════════════════════════╡
│ 0  TURRET        Servo glide · laser · serial protocol             │ Pico
└──────────────────────────────────────────────────────────────────┘
```

### One trigger, end to end

```
0 ms     Operator presses 2 (rack B). Phone in B starts playing the "UPS on battery" beep pattern
5 ms     Backend: incident "Rack B · UPS on battery · SCRIPTED" → TRIGGERED
10 ms    Aim controller sends LOCK,<angle_B>
~1-1.7 s Pico glides to B laser-off, blinks 3×, laser steady, replies POS,<deg>
         (simulated worst case, full sweep + blink, is ~1.7 s)
then     Backend: state LOCKED → dashboard B glows, phone gets the alert
         Acknowledge on the phone → ACKNOWLEDGED → laser off → CLEARED after 10 s of no beeps
```

### Layer 0: Turret (`beacon_turret.ino`)

- **Absolute angles.** `AIM,<deg>` tells the servo to be at an angle. The laptop never tracks where it currently is.
- **Eased motion.** Smoothstep glide, ~1° per 20 ms servo frame, duration scaled to distance. No snap, small current spikes.
- **Same-side approach.** Every aim runs fast to ~6° below the target, then creeps upward onto it. Backlash is identical every time, so a saved angle lands on the same spot.
- **`LOCK`** = laser off while travelling, 3 quick blinks on arrival, then steady. This is the lock-on look.
- **Failsafe.** Laser auto-off after 10 s unless `LASER,1` is re-sent.
- **The Pico makes no decisions.** It is a motor driver. All logic lives on the laptop.

### Layer 1: Ingest

Serial bridge (`pyserial`), both directions. For Tier 1+: recorder (CSV with rack label and session) and a replay simulator.

### Layer 2: Locator

```python
def locate(source) -> dict[str, float]:   # {"A": 0.0, "B": 1.0, ...}
```

Scripted version: hotkey → one-hot dict. A later rule or ML version replaces this function and **nothing downstream changes**. This is the literal basis for "in practice this is a model."

### Layer 3: Action

- **Incident manager.** States: `TRIGGERED → LOCKED → ACKNOWLEDGED → CLEARED`. Repeat triggers on one rack merge into one incident. Keeps history. Every incident carries `locator: "scripted"`.
- **Aim controller.** Looks up the rack's angle in `aim_points.json`, sends `LOCK,<deg>`, waits for `POS`. Laser off on Acknowledge or after 8 s. Only re-aims if the rack changes.
- **Notifier.** Pushes incident changes to the API.

### Layer 4: API (FastAPI)

| Endpoint | Purpose |
|---|---|
| `POST /trigger` `{rack}` | Scripted trigger (hotkeys call this). The alarm is always the one in `patterns.json` |
| `POST /clear` | Clear the active incident, laser off |
| `WS /live` | Events, incidents, turret position |
| `GET /layout`, `GET /incidents` | Rack positions, history |
| `POST /incidents/{id}/ack` | Phone's Acknowledge button |
| `POST /laser/jog` `{deg}`, `POST /calibrate/aim/{rack}` | Calibration (Section 9) |
| `GET /`, `GET /alert` | Dashboard and phone page |

### Layer 5: Presentation

- **Hotkeys:** `1`-`5` = racks A-E. `Esc` = clear.
- **Live tab:** top-down map with the selected rack glowing, a **SCRIPTED** badge, the incident card ("Rack B · UPS on battery · check upstream power"), turret angle, event log. A "Run demo sequence" button plays B → D → A.
- **Setup tab:** arrow-key jog, a save button per rack, a re-home button.
- **Approach tab:** static slide of the ML design (Appendix A). Shows a scatter plot of recorded log-ratios only if we actually recorded data.
- **Phone page:** QR code, big alert card plus **Acknowledge**. Run everything on a **phone hotspot**, since venue Wi-Fi often blocks phone-to-laptop traffic.

### The alarm (`patterns.json`)

The demo uses **one alarm**, based on APC's documented UPS alarms ([APC FAQ](https://www.se.com/us/en/faqs/FA156554/)), with the timing shortened for the demo.

| Pattern | Sound | Meaning | Action |
|---|---|---|---|
| P1 | 4 short beeps, then a pause (really every 30 s, ~5 s in the demo) | UPS on battery | Check upstream power / generator |

It is hardcoded: every trigger shows this alarm, and the phone in the rack plays the matching WAV so the sound agrees with the screen. `patterns.json` stays a file with one entry so more alarms (low battery, overload) can be added without code changes. In Tier 1, a rule-based decoder could confirm P1 from real beep timing.

---

## 6. Disclosure (say this, don't hide it)

**Opening line to judges:** "The rack location in this demo is scripted. Everything you'll see after that, the laser, the dashboard, the phone alert, is real and running. Here's the design for the ML locator and why we'd build it that way."

- The SCRIPTED badge stays on screen for the whole demo.
- No confidence percentages anywhere.
- Never describe a scripted trigger as "detected."
- Only quote numbers we actually measured.

---

## 7. Data contracts

```text
Laptop → Pico   AIM,<deg>  |  LOCK,<deg>  |  LASER,<0|1>  |  JOG,<deg>  |  HOME  |  POS?
Pico → laptop   READY  |  POS,<deg>  |  OK,LASER  |  ERR,<reason>
```

Incident (layer 3 → 4 → 5):

```json
{"id":"inc_17","state":"LOCKED","rack":"B","locator":"scripted",
 "alarm":{"device":"UPS","meaning":"On battery","action":"Check upstream power","pattern":"P1"},
 "first_seen":"02:13:07","turret_deg":78.2}
```

`aim_points.json` (starting guesses only, calibrate for real):

```json
{"A": 48.0, "B": 66.0, "C": 90.0, "D": 114.0, "E": 132.0}
```

| File | Contents |
|---|---|
| `rack_layout.json` | Rack and mic positions |
| `aim_points.json` | Pan angle per rack |
| `patterns.json` | The one alarm (P1, UPS on battery) |
| `beeps/*.wav` | Beep sounds for the phone |
| *Tier 1+:* `recordings/*.csv`, `metrics.json` | Recorded beeps, results |

### Tech stack

- **Firmware:** Arduino IDE + arduino-pico core, `Servo` library
- **Backend:** Python 3, `pyserial`, `FastAPI`, `uvicorn`
- **Frontend:** HTML/JS or React (Vite), SVG map
- **SpacetimeDB:** skipped, unless their sponsors confirm a Python-heavy backend still qualifies

---

## 8. Tasks

| Stream | In order |
|---|---|
| **A: Hardware** | A1 wire servo + laser circuit + power → A2 flash `beacon_turret.ino`, test by typing `LOCK,90` in the serial monitor → A3 glue laser to servo arm, fixed downward angle → A4 5 boxes, turret taped down, calibrate (Section 9) → *A5 Tier 1: mic test at 40 cm* |
| **B: Backend** | B1 serial bridge + `aim()` → B2 `aim_points.json` + jog/calibrate endpoints → B3 `/trigger` + incident manager → B4 hotkeys + demo sequence → B5 WebSocket → *B6 Tier 1: beep detector* |
| **C: Frontend + pitch** | C1 Live tab (SCRIPTED badge) → C2 phone page + QR → C3 Setup tab → C4 Approach slide → C5 2-minute pitch with the disclosure line |
| **D: Everyone** | D1 full live run → D2 hotspot test with a stranger's phone → **D3 20 triggers, count how many dots land on the right box, write the number down** → D4 screen-record a perfect run as backup |

**Critical path:** wire + power → turret test → boxes + calibration → trigger flow. Everything else runs in parallel.

---

## 9. Calibration (≈10 min, redo whenever anything moves)

1. Park at `HOME` (90°), laser off.
2. Turn the laser on and jog with the arrow keys (`JOG,±1`). **Land every target moving upward in angle**, the same direction the firmware approaches, so the saved angle matches what the firmware reproduces.
3. Stop when the dot sits on the middle of the box opening. Save it for that rack.
4. Repeat A → E, then run all five in random order twice. If any dot is off the box, redo that rack.
5. Starting guesses: with the turret ~40 cm back and racks ~18 cm apart, expect roughly 90° ± 24° and ± 42°. Don't trust them.

Tolerance: 1° ≈ 0.7 cm at 40 cm, and the boxes are 15 cm wide, so ±4° or so is still a hit.

---

## 10. Top risks

| Risk | Plan |
|---|---|
| Dot misses a box | Calibrate under venue lighting, tape the turret down, recalibrate after any move, run the 20-trigger test |
| Servo jitter or brownout | Glide motion, shared ground, capacitor |
| Can't connect the battery to the power module | Power from VBUS with the capacitor |
| Laser bright in a lit hall | Calibrate at the demo spot, dim the table lamp if needed |
| Judges read scripted as deceptive | Say it first, SCRIPTED badge, no fake confidence, show the real turret metrics |
| Phone can't reach the laptop | Phone hotspot |

---

## 11. Judge Q&A cheat sheet

| Question | Answer |
|---|---|
| "Is the location real?" | No, it's scripted for this demo, and we said so up front. The turret, dashboard and alerts are real. The locator is one function behind a fixed interface, so a model drops in without touching anything else. |
| "Why only one alarm?" | Scope. Beep codes are defined by the manufacturer, so more alarms are just more entries in `patterns.json`, not new code. We built the loop that finds the device first. |
| "Why not build the ML?" | Time. We chose to build the physical loop properly and measure it. The ML design and its known difficulty are on the Approach tab. |
| "How would the ML work?" | Classify 5 racks from the level ratios between 3 mics, trained on recorded beeps and tested on a separate session. Compare against loudest-mic and weighted-centroid baselines. See Appendix A. |
| "Is it really zero integration?" | The design is. A few sensors cover a row, nothing attached to racks or connected to devices. |
| "Why SNMP isn't enough?" | These devices don't have it. That's exactly why they beep. |
| "What did you measure?" | Dot hit rate over 20 triggers: [fill in the real number]. |

---

## Appendix A: ML locator design (not built)

**Task.** Classify {A, B, C, D, E, NONE} from the inter-mic level fingerprint.

**Why it's hard, honestly.** With mics ~40 cm from the box fronts and racks ~18 cm apart, the L/M level ratio only steps about 2.6 dB between adjacent racks (about +2.6, 0, −2.6 for A, B, C). Mics closer in (~15 cm) widen that to about 8 dB. A single 2500 Hz tone also fades in space (wavelength ~14 cm, about the size of a box), so a couple of cm of phone movement can swing the level several dB. Training data must vary phone placement, not just angle and volume.

**Features (19 per beep):** average, share, log-ratio, peak, SNR and purity per mic, plus duration. If level features separate badly, add sin/cos of the inter-mic phase from the Goertzel output.

**Models and baselines:** loudest mic (cannot name B or D), weighted centroid (best non-ML), random forest / kNN (the model). The model has to beat both.

**Data:** ~40 beeps per rack plus ~40 NONE (claps, talking, fan only), in 2 separate sessions. Train on session 1, test on session 2. Report accuracy and a confusion matrix for all three methods. Uncertainty: top probability under 0.6 → "between B and C". Smooth with a running vote across beeps.

**Rule:** never touch the mics' sensitivity knobs after training.
