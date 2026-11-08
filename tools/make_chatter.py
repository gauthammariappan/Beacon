#!/usr/bin/env python3
"""Builds the crowd-chatter background track (beeps/beacon_background_chatter.wav, 15 minutes)
from the Mac's built-in voices talking over each other. macOS only (uses `say` and `afconvert`).

  python3 tools/make_chatter.py
"""
import os
import random
import subprocess
import tempfile
import wave

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
RATE = 22050
MINUTES = 15
LINES = """Did you see the keynote this morning?
Where did they put the pizza?
I think our demo is at four thirty.
Can you push your branch so I can pull it?
The wifi keeps dropping for me.
Okay so the backend is finally working.
Wait, which table are the judges at?
I need more coffee honestly.
Did anyone grab extra cables from the desk?
That team over there built a robot dog.
We should practice the pitch one more time.
How long have you been awake?
I'll take the slides, you do the live part.
Is the hardware desk still open?
My laptop is about to die, where's a charger?
That looks really cool, how does it work?
We switched our whole idea at midnight.
Can I borrow your screwdriver for a second?
The sponsor said they want something practical.
Let's go get food before the line gets long.
I think the bug was in the serial code.
Okay, try it again, I changed one line.
Do you know when submissions close?
We need a better name for this project.
The judges are walking this way.
Honestly this is going better than last year.
Can you hold this while I tape it down?
Wait, say that again, I didn't hear you.
I'm going to grab some water, want anything?
That was so loud, what was that?""".split("\n")
VOICES = ["Samantha", "Daniel", "Karen", "Moira", "Rishi", "Tessa", "Fred",
          "Eddy (English (US))", "Flo (English (US))", "Reed (English (US))",
          "Sandy (English (US))", "Shelley (English (US))"]


def main():
    random.seed(3)
    tracks = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, voice in enumerate(VOICES):
            lines = LINES[:]
            random.shuffle(lines)
            aiff, wav = os.path.join(tmp, f"v{i}.aiff"), os.path.join(tmp, f"v{i}.wav")
            subprocess.run(["say", "-v", voice, "-r", str(random.randint(170, 210)), "-o", aiff,
                            " [[slnc 700]] ".join(lines)], check=True)
            subprocess.run(["afconvert", "-f", "WAVE", "-d", f"LEI16@{RATE}", "-c", "1", aiff, wav], check=True)
            with wave.open(wav) as w:
                tracks.append(np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(float) / 32768)
            print(f"voice {voice}: {len(tracks[-1]) / RATE:.0f} s")

    total = RATE * 60 * MINUTES
    mix = np.zeros(total)
    for t in tracks:
        gain = random.uniform(0.35, 0.9)
        pos = random.randint(0, len(t))
        while pos < total:                    # keep every voice going for the whole track
            seg = t[: total - pos]
            mix[pos:pos + len(seg)] += gain * seg
            pos += len(t) + random.randint(0, RATE * 20)

    # a little room tone underneath (pink noise)
    rng = np.random.default_rng(0)
    n = RATE * 30
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / RATE)
    f[0] = f[1]
    room = np.fft.irfft(spec / np.sqrt(f), n)
    mix += 0.04 * np.tile(room / np.max(np.abs(room)), total // n + 1)[:total]
    mix = mix / np.max(np.abs(mix)) * 0.8

    os.makedirs(os.path.join(ROOT, "beeps"), exist_ok=True)
    out = os.path.join(ROOT, "beeps", "beacon_background_chatter.wav")
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((mix * 32767).astype(np.int16).tobytes())
    print(f"wrote {os.path.relpath(out, ROOT)} ({MINUTES} min)")


if __name__ == "__main__":
    main()
