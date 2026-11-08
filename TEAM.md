# Beacon: Team Plan v3 (scripted locator)

Matches `ARCHITECTURE.md` v3.0. **Which rack is beeping is picked by an operator hotkey**, not predicted. Everything after that is real: the laser turret, the incident flow, the dashboard and the phone alert. The mics are an optional extra (Tier 1), only after the demo works end to end.

The old plan (3 on hardware, 1 on ML) is saved as `TEAM_v2.md`.

---

## Where the hardware is right now

| Piece | Status |
|---|---|
| Arduino IDE + Pico board package, first upload (Blink) | ✅ Done |
| Servo wired, tested (swings on command) | ✅ Done |
| Laser switch (transistor + resistor) wired, tested (blinks on command) | ✅ Done |
| All together on USB power: servo moving, laser on, **0 Pico restarts** | ✅ Done |
| Turret built (laser on the servo arm, wedge, base, raised) | ⏳ In progress |
| Turret firmware `beacon_turret.ino` (glide, LOCK blink, failsafe) | ❌ Not written yet (Claude writes it) |
| 5 boxes built and taped down, turret placed | ❌ Not started (as far as we know) |
| Calibration (5 aim angles) + 20-trigger hit test | ❌ Needs the two rows above |
| *Tier 1:* mic L, 2500 Hz filter at 40 cm: **81× above quiet, 117× with the servo moving** | ✅ Done (head start) |
| *Tier 1:* mics M and R + long wires | ❌ Optional, later |

**Tier 0 (must-have) hardware: about 45% done.** The remaining 55%: the turret build, the turret firmware, the boxes, then calibration and the hit test.

---

## Roles

Put names next to these. The Pico and turret stay plugged into **this laptop**, which is also the demo laptop.

| Role | Was | Now does |
|---|---|---|
| **Turret** (at this laptop) | Laser turret | Finish the turret, flash the turret firmware, calibrate, run the hit test |
| **Builder** | Build + wiring check | 5 boxes, tape-down, turret stand, demo phones and hotspot, then helps with the pitch |
| **Backend** | Machine learning | Serial bridge, aim points, trigger + incident flow, hotkeys, WebSocket |
| **Frontend + pitch** | Pico + mics | Dashboard (Live / Setup / Approach), phone page, the 2-minute pitch |

---

## Wiring as built (this is what's on the Pico now)

Everything runs on the laptop's USB power. The battery pack and power module aren't needed: our combined test had the servo moving and the laser on with zero restarts. That's the VBUS option in `ARCHITECTURE.md` Section 4.

Pico upside down (pins pointing up), USB at the top:

```
                    [ USB ]
LEFT side                          RIGHT side
 1st  VBUS     ← servo RED           4th from top    GP2   ← mic L +    (Tier 1)
 3rd  GND      ← transistor LEFT leg (E)
 5th  3V3(OUT) ← laser S
10th  GP26     ← mic L A0 (Tier 1)    4th from bottom GP13 ← resistor → transistor MIDDLE leg (B)
13th  GND      ← mic L G  (Tier 1)    3rd from bottom GND  ← servo BROWN
                                      very bottom     GP15 ← servo YELLOW (signal)

Off the Pico:  transistor RIGHT leg (C) → laser −      laser middle pin → empty
```

**Never use:** 3V3_EN (left, 4th from top), VSYS (left, 2nd), RUN.

---

## Turret person (this laptop)

### T1. Finish the turret build (30 min)
1. **Unplug the USB.**
2. Fold a small cardboard **wedge**, about 2 × 3 cm, so one end is **3–5 mm thick**.
3. Put the wedge on the servo arm: **thick end over the shaft**, thin end toward the tip.
4. Put the laser on the wedge: **gold lens pointing out past the arm's tip**, pins toward the shaft. **Tape it first** so you can adjust it.
5. Tape the laser's wires loosely along the arm, with a small loop of slack so they don't pull when it swings.
6. Tape the servo's blue body to a cardboard base, shaft pointing up.
7. Raise the base on a small box, so the beam can travel over anything sitting between the turret and the boxes.

### T2. Flash the turret firmware (15 min)
1. Claude writes `firmware/beacon_turret/beacon_turret.ino` and uploads it from this laptop.
2. Test it in **Tools → Serial Monitor**, at **115200**, with line ending set to **Newline**:
   - It prints `READY` when it starts.
   - `HOME` → the servo glides to the middle (90°).
   - `LOCK,90` → the laser stays off while moving, blinks 3 times on arrival, then stays on, and the Pico replies `POS,90`.
   - `LASER,0` → the laser turns off.
   - Leave the laser on and wait: it switches itself off after **10 seconds** (the failsafe).
3. **Close the Serial Monitor** when you're done. Only one program can use the Pico at a time.

### T3. Place it (with the Builder)
1. Put the turret about **40 cm back from rack C**, centered on it.
2. Tape the base down, and **draw a tape outline** around it so it can go back in the same spot if bumped.

### T4. Calibrate the 5 racks (10 min)
Do this at the demo spot, under the venue lighting.
1. `HOME`, then `LASER,1`.
2. For each rack, A to E:
   - Start from its guess: `AIM,48` (A), `AIM,66` (B), `AIM,90` (C), `AIM,114` (D), `AIM,132` (E).
   - Nudge with `JOG,1` / `JOG,-1` until the dot sits in the **middle of the box opening**. Always finish with a `JOG,1` (an **upward** move), because that's the direction the firmware approaches from.
   - Send `POS?` and write down the angle it replies with.
3. Put the five angles in `config/aim_points.json`, for example `{"A": 47.0, "B": 66.0, ...}`.
4. Send `LOCK,<angle>` for all five racks in random order, twice. If a dot misses a box, redo that rack.
5. **Recalibrate any time the turret or a box moves.**

### T5. The 20-trigger hit test (10 min)
1. Twenty `LOCK` commands to random racks.
2. Count how many dots land on the right box, and **write the number down**. This is the measured number for the pitch.

### T6. Hand off
- Give the Backend person `aim_points.json` and the command list (`ARCHITECTURE.md` Section 7).
- The turret stays plugged into this laptop for the rest of the hackathon.

### T7 (Tier 1, only after the demo works end to end): mics M and R
Mic M: A0 → GP27, + → GP3, G → AGND. Mic R: A0 → GP28, + → GP4, G → a free GND. They need the long wires from `TEAM_v2.md`.

---

## Builder

1. **Boxes:** 5 boxes about 15 cm wide, 3 cm gaps, in a straight row. Cut a phone-sized opening in each front, facing the turret. **Label them A to E, large enough for judges to read.**
2. **Tape the boxes down** and draw tape outlines around each one.
3. **Turret stand:** a small box for the turret, placed with the Turret person (T3).
4. **Demo kit:**
   - **Beeper phone** with the "UPS on battery" WAV (P1). Claude can generate it on this laptop.
   - **Fan-noise phone:** search "server room noise".
   - **Phone hotspot:** iPhone with "Maximize Compatibility" on. The laptop and the demo phones all join it.
5. **Then help Frontend with the pitch,** and practice being the "operator" who presses the hotkeys.

## Backend (was ML)

Build these against a **fake turret** first: a few lines that answer `POS,<deg>` to every `LOCK`, so you don't need the Pico on your laptop. Switch to the real one on this laptop at the end.

1. **Serial bridge + `aim()`:** pyserial at 115200 on `/dev/cu.usbmodem…`. Sends `AIM` / `LOCK` / `LASER` / `JOG` / `HOME` / `POS?`, and reads `READY` / `POS` / `OK` / `ERR`.
2. **`aim_points.json`** plus `POST /laser/jog` and `POST /calibrate/aim/{rack}`.
3. **`POST /trigger {rack}` + incident manager:**
   - States: `TRIGGERED → LOCKED → ACKNOWLEDGED → CLEARED`.
   - Every incident carries `locator: "scripted"`.
   - Always the one alarm from `patterns.json`.
   - Laser off on Acknowledge, or after 8 s.
4. **Hotkeys:** `1`–`5` = racks A–E, `Esc` = clear, plus a "Run demo sequence" that plays B → D → A.
5. **WebSocket `/live`:** events, incidents, turret angle.
6. **`locate()`:** today it's the hotkey returning a one-hot dict. It's the swap point for Tier 1 and 2 later.
7. *Tier 1 later:* the beep detector, which works at 81× on mic L.

## Frontend + pitch (was mics)

1. **Live tab:**
   - rack map with the selected rack glowing
   - a **SCRIPTED badge** that stays on screen
   - incident card ("Rack B · UPS on battery · check upstream power")
   - turret angle, event log, and the "Run demo sequence" button
   - **no confidence percentages anywhere**
2. **Phone page + QR code:** a big alert card plus **Acknowledge**.
3. **Setup tab:** arrow-key jog, a Save button per rack, and a Re-home button.
4. **Approach tab:** one slide of the ML design (`ARCHITECTURE.md` Appendix A).
5. **2-minute pitch,** opening with the disclosure line: *"The rack location in this demo is scripted. Everything you'll see after that, the laser, the dashboard, the phone alert, is real and running."*

---

## Everyone, at the end

1. **Full live run:** hotkey → laser locks on → dashboard glows → phone alert → Acknowledge → laser off.
2. **Hotspot test** with a phone that isn't yours.
3. **20-trigger hit test** through the real flow. Write the number down.
4. **Screen-record a perfect run** as a backup.
5. **After judging:** return every part to the HackUTD desk to get the license back.

## Checkpoints

1. **Turret firmware works:** `LOCK,90` glides, blinks and holds.
2. **Calibrated:** all 5 racks hit, twice in random order.
3. **End to end:** a hotkey triggers the laser, the dashboard and the phone.
4. **Rehearsed:** 20-trigger number written down, backup video recorded.
