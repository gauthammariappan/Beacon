#!/usr/bin/env python3
"""Live Beacon locator, no GUI.

Press Enter: it listens to the mics, runs every clear beep through the model, votes over 4 beeps,
then sends AIM,<angle> for that box and turns the laser on.

  python3 tools/live.py                                       live, with the Pico
  python3 tools/live.py --replay data/recordings/session2_E.csv  try the logic on a recording (no Pico)

Angles come from config/aim_points.json (A 119, B 99, C 68, D 40, E 23).
It also serves a live alert page for phones on the same Wi-Fi/hotspot (the address is printed at start).
"""
import argparse
import csv
import json
import os
import signal
import sys
import time

import joblib
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
from beacon.detect import BeepDetector                                 # noqa: E402
from beacon.features import RACKS, RATIO_IDX, beep_features, is_clear  # noqa: E402
from beacon.frames import FIELDS, parse_e_line                         # noqa: E402

DEFAULT_ANGLES = {"A": 119.0, "B": 99.0, "C": 68.0, "D": 40.0, "E": 23.0}


def load_angles():
    try:
        with open(os.path.join(ROOT, "config", "aim_points.json")) as f:
            saved = {k: float(v) for k, v in json.load(f).items()}
    except (OSError, ValueError):
        saved = {}
    return {r: saved.get(r, DEFAULT_ANGLES[r]) for r in RACKS}


class Locator:
    """Beep detector + model + vote. Feed it frames; it tells you when it has decided."""

    def __init__(self, bundle, vote):
        self.model = bundle["model"]
        self.which = bundle["features"]
        self.classes = list(self.model.classes_)
        self.vote = vote
        self.reset()

    def reset(self):
        self.det = BeepDetector()
        self.probs = []

    def push(self, ms, v):
        beep = self.det.push(ms, v)
        if not beep:
            return None
        feats = beep_features(beep)
        if not is_clear(feats):
            return "faint", None
        x = feats[RATIO_IDX] if self.which == "ratio" else feats
        p = self.model.predict_proba([x])[0]
        info = {"levels": np.exp(feats[0:3]), "p": p}
        if self.classes[int(np.argmax(p))] == "NONE":
            return "not_a_beep", info
        self.probs.append(p)
        info["n"] = len(self.probs)
        if len(self.probs) < self.vote:
            return "beep", info
        mean = np.mean(self.probs, axis=0)
        ranked = sorted(((c, mean[i]) for i, c in enumerate(self.classes) if c != "NONE"), key=lambda kv: -kv[1])
        info["box"], info["ranked"] = ranked[0][0], ranked
        return "done", info

    def top2(self, p):
        order = np.argsort(-p)
        return "  ".join(f"{self.classes[i]} {p[i]:.0%}" for i in order[:2])


def beep_line(loc, kind, info, vote):
    lv = info["levels"]
    return (f"  beep {info['n']}/{vote}   L {lv[0]:.2f}  M {lv[1]:.2f}  R {lv[2]:.2f}   "
            f"model says: {loc.top2(info['p'])}")


def decision_lines(info, angles):
    ranked = "   ".join(f"{b} {s:.0%}" for b, s in info["ranked"][:3])
    return [f"\n  >>> BOX {info['box']}   (vote: {ranked})",
            f"  >>> AIM,{angles[info['box']]:g}  then  LASER,1"]


def send_and_wait(pico, cmd, prefix, timeout=8.0):
    """Send a command and wait for the reply that starts with `prefix`, skipping mic lines."""
    pico.write(cmd)
    end = time.time() + timeout
    while time.time() < end:
        for line in pico.lines(0.1):
            if line.startswith(prefix) or line.startswith("ERR"):
                return line
    return None


def listen_once(pico, loc, angles, timeout, hub=None):
    loc.reset()
    send_and_wait(pico, "LASER,0", "OK", 2)
    if hub:
        hub.listening(loc.vote)
    pico.write("MIC,1")
    end = time.time() + 0.3
    while time.time() < end:          # drop anything left over
        pico.lines(0.05)
    print("  Listening... play the beep in any box.")
    start = time.time()
    while time.time() - start < timeout:
        for line in pico.lines(0.1):
            parsed = parse_e_line(line)
            if not parsed:
                continue
            out = loc.push(*parsed)
            if not out:
                continue
            kind, info = out
            if kind == "not_a_beep":
                print("  (heard a sound that isn't the beep, ignored)")
            elif kind in ("beep", "done"):
                print(beep_line(loc, kind, info, loc.vote))
                if hub and kind == "beep":
                    hub.beep(info["n"])
            if kind == "done":
                pico.write("MIC,0")
                for text in decision_lines(info, angles):
                    print(text)
                pos = send_and_wait(pico, f"AIM,{angles[info['box']]:g}", "POS")
                ok = send_and_wait(pico, "LASER,1", "OK")
                if hub:
                    hub.incident(info["box"], info["ranked"], angles[info["box"]], loc.vote)
                if pos and pos.startswith("POS") and ok:
                    print(f"  Laser ON, pointing at box {info['box']} ({pos}).")
                else:
                    print(f"  The Pico didn't confirm the move (got {pos!r}, {ok!r}). Is the turret firmware on it?")
                return info["box"]
    pico.write("MIC,0")
    print(f"  No clear beep in {timeout:g} s. Is the beeper playing, at full volume, speaker toward the opening?")
    if hub:
        hub.no_beep(f"No alarm heard in the last {timeout:g} s.")
    return None


def replay(path, loc, angles):
    with open(path) as f:
        rows = list(csv.DictReader(f))
    print(f"Replaying {os.path.relpath(path, ROOT)} (recorded in box {rows[0]['label']}), no Pico involved")
    decisions = []
    for r in rows:
        out = loc.push(int(r["pico_ms"]), [float(r[k]) for k in FIELDS])
        if out and out[0] == "done":
            decisions.append(out[1]["box"])
            for text in decision_lines(out[1], angles):
                print(text)
            loc.probs = []            # start the next vote, keep the detector running like a long listen
    if decisions:
        right = sum(d == rows[0]["label"] for d in decisions)
        print(f"\n{len(decisions)} decisions: {right} pointed at the right box ({right / len(decisions):.0%})")
    else:
        print("No decisions in this recording.")


def _stop_on_signal(signum, frame):
    raise KeyboardInterrupt


def main():
    ap = argparse.ArgumentParser(description="Listen, locate the beeping box, aim the laser")
    ap.add_argument("--vote", type=int, default=4, help="beeps to combine before aiming")
    ap.add_argument("--timeout", type=float, default=30, help="seconds to listen before giving up")
    ap.add_argument("--model", default=os.path.join(ROOT, "model", "locator.joblib"))
    ap.add_argument("--replay", help="run on a recorded CSV instead of the live mics")
    ap.add_argument("--port")
    ap.add_argument("--web-port", type=int, default=8787, help="port for the phone page (next free one is used if taken)")
    ap.add_argument("--no-web", action="store_true", help="don't serve the phone page")
    args = ap.parse_args()

    if not os.path.exists(args.model):
        raise SystemExit("No model yet. Run: python3 tools/train.py")
    bundle = joblib.load(args.model)
    angles = load_angles()
    loc = Locator(bundle, args.vote)
    print(f"Model: {bundle['name']}   vote over {args.vote} beeps")
    print("Laser angles: " + "  ".join(f"{b} {angles[b]:g}" for b in RACKS))

    if args.replay:
        replay(args.replay, loc, angles)
        return

    from beacon.serial_port import PicoSerial
    pico = PicoSerial(args.port)
    # closing the Terminal window (SIGHUP) or a plain kill (SIGTERM) shuts down like Ctrl+C: laser off
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, _stop_on_signal)
    hub = None
    if not args.no_web:
        from beacon.hub import Hub, lan_ip, start_server
        hub = Hub(RACKS, on_ack=lambda: pico.write("LASER,0"))
        try:
            web = start_server(hub, args.web_port)
            print(f"\nPhone alerts: open  http://{lan_ip()}:{web.beacon_port}  on a phone on the same Wi-Fi/hotspot")
            print(f"QR code for judges: open  http://localhost:{web.beacon_port}/qr  on this laptop")
        except OSError as e:
            print(f"(Couldn't start the phone page: {e})")
            hub = None
    try:
        while True:
            cmd = input("\nPress Enter to listen  (o + Enter = laser off, q + Enter = quit): ").strip().lower()
            if cmd == "q":
                break
            if cmd == "o":
                send_and_wait(pico, "LASER,0", "OK", 2)
                if hub:
                    hub.acknowledge("laptop")
                print("  Laser off.")
                continue
            listen_once(pico, loc, angles, args.timeout, hub)
    except (KeyboardInterrupt, EOFError):
        print()
    finally:
        pico.write("MIC,0")
        pico.write("LASER,0")
        pico.close()
        print("Stopped. Laser off.")


if __name__ == "__main__":
    main()
