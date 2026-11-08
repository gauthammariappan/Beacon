# Beacon

Beacon finds which server rack an unmonitored alarm is beeping from, points a laser at it, and alerts a technician's phone. Built at HackUTD for the NMC² challenge.

In a loud data hall, a UPS or PDU that isn't wired into monitoring can only warn people by beeping, and nobody can tell which rack the beep is coming from. Beacon listens with a few cheap microphones, works out the rack, and tells someone to go check it.

## How it works

1. **Three microphones** sit in front of racks A, C and E in a row of five racks. Racks B and D have no microphone of their own.
2. **A Raspberry Pi Pico 2 W** samples all three microphones 16,000 times a second and measures how loud the alarm's 2500 Hz tone is at each one (a Goertzel filter, with 2000 and 3000 Hz as reference bands). It streams those levels to the laptop.
3. **On the laptop**, each beep becomes 19 loudness features (levels, shares and ratios between the microphones). A random forest trained on recorded beeps says which rack it came from, and the system votes over 4 beeps before deciding.
4. **The Pico swings a servo-mounted laser** to that rack and turns it on.
5. **A phone page** shows "Server Rack B might have an issue. Check it out." Tapping **Mark as Checked** turns the laser off and logs who handled it and how fast.

## Results

Trained on recording session 1, tested on session 2 (which the model never saw):

| Method | Accuracy on rack beeps |
|---|---|
| Loudest microphone (baseline; it can never name racks B or D) | 57% |
| Weighted centroid (baseline) | 55% |
| Random forest, single beep | 64% |
| **Random forest, 4-beep vote** | **70%** |
| Right rack in the model's top two | 88% |

Most mistakes are one rack off. Rack E is the easiest, and rack C (in the middle) is the hardest.

## Hardware

Raspberry Pi Pico 2 WH, 3 sound sensor modules, an SG90 servo, a laser module switched by a 2N2222 transistor and a 1k resistor. Everything runs on the laptop's USB power.

| Part | Pico pin |
|---|---|
| Mic L (in front of rack A): A0 / + / G | GP26 / GP2 / GND |
| Mic M (in front of rack C): A0 / + / G | GP27 / GP3 / AGND |
| Mic R (in front of rack E): A0 / + / G | GP28 / GP4 / GND |
| Servo signal / + / ground | GP15 / VBUS / GND |
| Laser switch: GP13 → 1k → transistor base; emitter to GND; collector to laser −; laser S | 3V3(OUT) |

The microphones are powered from GPIO pins set HIGH, so no breadboard is needed.

## Running it

1. **Firmware:** open `firmware/beacon_turret/beacon_turret.ino` in the Arduino IDE with the arduino-pico core (board: Raspberry Pi Pico 2W) and upload it. Serial commands include `AIM,<deg>`, `LOCK,<deg>`, `JOG,<deg>`, `HOME`, `SETHOME`, `LASER,<0|1>` and `MIC,<0|1>`.
2. **Python:** `pip install -r requirements.txt` (macOS or Linux; the serial code uses termios).
3. **Sounds for the phones:** `python3 tools/make_beeps.py` writes the alarm beeps, and `python3 tools/make_chatter.py` writes a background-chatter track (macOS). Both go into `beeps/`.
4. **Live demo (mics and model):** `python3 tools/live.py`. Press Enter to listen. It prints an address to open on a phone on the same Wi-Fi or hotspot, and `http://localhost:8787/qr` on the laptop shows a QR code for it.
5. **Remote (no mics, no model):** `python3 tools/remote.py`. It serves the same alert page, plus a remote at `/control` for a second phone: tap a rack, the laser points at it, and the alert goes out. `http://localhost:8787/qr?control` shows a QR code for the remote.
6. **Laser angles** for each rack are in `config/aim_points.json`.

Only one script can use the Pico at a time. If another one already has it, the new one stops and says which.

## Recording and training

The recordings are not in this repo. `RECORDING.md` explains how to record a new dataset with `tools/record.py`. Then `python3 tools/train.py` trains on session 1, tests on session 2, prints the comparison above, and writes `model/locator.joblib` (the model trained on our recordings is included).

## Layout

| Path | What it is |
|---|---|
| `firmware/beacon_turret/` | The Pico firmware: microphones, servo and laser |
| `firmware/tests/` | Small sketches used to test each part on its own |
| `beacon/` | Beep detection, features, the serial link, and the phone page server (`hub.py`, `web/`) |
| `tools/` | `record.py`, `train.py`, `live.py` (mics and model), `remote.py` (phone remote, no mics or model), and the sound generators |
| `config/aim_points.json` | Laser angle for each rack |
| `model/` | The trained model and its test results |
| `TEAM.md`, `RECORDING.md` | How the team built the hardware and recorded the data |
| `ARCHITECTURE.md` | An earlier plan, where the rack was chosen with a hotkey. The code in this repo uses the trained model instead. |
