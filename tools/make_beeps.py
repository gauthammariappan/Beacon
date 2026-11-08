# Writes the beep WAVs for the beeper phone into beeps/.
# Run from the project folder:  python3 tools/make_beeps.py
import os
import wave
import numpy as np

RATE = 22050   # plenty for a 2500 Hz tone, and keeps the files small
FREQ = 2500


def tone(sec):
    t = np.arange(int(RATE * sec)) / RATE
    y = np.sin(2 * np.pi * FREQ * t)
    # 5 ms fade in and out so the phone speaker doesn't click
    n = int(0.005 * RATE)
    ramp = np.linspace(0, 1, n)
    y[:n] *= ramp
    y[-n:] *= ramp[::-1]
    return y


def silence(sec):
    return np.zeros(int(RATE * sec))


def save(name, pattern, minutes):
    one = np.concatenate(pattern)
    repeats = int(minutes * 60 * RATE / len(one)) + 1
    y = np.tile(one, repeats)
    os.makedirs("beeps", exist_ok=True)
    path = f"beeps/{name}.wav"
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((y * 0.9 * 32767).astype(np.int16).tobytes())
    print(f"{path}: {len(y) / RATE / 60:.1f} min")


# the demo + training sound: APC "on battery", 4 short beeps then a pause (really every 30 s, shortened)
save("beacon_P1_on_battery", [tone(0.15), silence(0.15)] * 4 + [silence(4.0)], minutes=3)
# quick-test sound: one short beep every second
save("beacon_steady_1s", [tone(0.15), silence(0.85)], minutes=3)
