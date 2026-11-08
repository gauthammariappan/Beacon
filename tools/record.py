#!/usr/bin/env python3
"""Records labeled training data for the Beacon rack locator.

  python3 tools/record.py --session 1                  walks you through A, B, C, D, E, then NONE
  python3 tools/record.py --label B --session 1        just one box (to redo it)

Each box is its own file: data/recordings/session<N>_<label>.csv (never overwrites; adds _2, _3 ...).
A box stops by itself after 40 beeps (10 spots x 4 beeps). NONE records 60 s of claps and talking.
"""
import argparse
import csv
import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
from beacon.detect import BeepDetector          # noqa: E402
from beacon.features import beep_features, is_clear  # noqa: E402
from beacon.frames import FIELDS, parse_e_line  # noqa: E402
from beacon.serial_port import PicoSerial       # noqa: E402

BOXES = ["A", "B", "C", "D", "E"]
LABELS = BOXES + ["NONE"]
SPOTS = ["middle, speaker toward the opening", "pushed to the back", "against the left wall",
         "against the right wall", "just inside the opening", "standing upright",
         "lying flat (or tilted back)", "tilted, speaker up", "angled toward the left",
         "angled toward the right"]


def free_path(path):
    if not os.path.exists(path):
        return path
    k = 2
    while os.path.exists(path.replace(".csv", f"_{k}.csv")):
        k += 1
    return path.replace(".csv", f"_{k}.csv")


def record_one(pico, label, session, beeps, seconds):
    """Records one box (or NONE). Returns (count, lost, path)."""
    is_none = label == "NONE"
    limit = seconds or (60 if is_none else 150)
    out_dir = os.path.join(ROOT, "data", "recordings")
    os.makedirs(out_dir, exist_ok=True)
    path = free_path(os.path.join(out_dir, f"session{session}_{label}.csv"))

    pico.write("LASER,0")
    pico.write("MIC,1")
    end = time.time() + 0.3
    while time.time() < end:          # throw away anything left over from before
        pico.lines(0.05)
    det = BeepDetector(require_purity=not is_none, min_frames=1 if is_none else 3)

    print(f"\n  Recording {'NONE (no beeps!)' if is_none else 'box ' + label}, session {session}. "
          "Stay quiet for a second while it listens to the room...")
    frames = count = 0
    said_ready = warned = done = lost = False
    start = last_data = time.time()
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "pico_ms"] + FIELDS + ["label", "session"])
        try:
            while not done and time.time() - start < limit:
                try:
                    lines = pico.lines(0.1)
                except ConnectionError:
                    lost = True
                    break
                if frames and time.time() - last_data > 2:
                    lost = True
                    break
                for line in lines:
                    parsed = parse_e_line(line)
                    if not parsed:
                        continue
                    ms, v = parsed
                    frames += 1
                    last_data = time.time()
                    w.writerow([f"{time.time():.3f}", ms] + [f"{x:.4f}" for x in v] + [label, session])
                    beep = det.push(ms, v)
                    if det.floor is not None and not said_ready:
                        said_ready = True
                        if is_none:
                            print("  READY. For 60 seconds: clap, talk, laugh, tap the table near every box. NO beeps.")
                        else:
                            print(f"  READY. Press PLAY now, slide the phone into box {label}, spot 1: {SPOTS[0]}. Hands out.")
                    if beep and not is_none and not is_clear(beep_features(beep)):
                        print("      (too faint or just chatter, not counted)")
                        beep = None
                    if beep:
                        count += 1
                        m = [sum(fr[1][i] for fr in beep["frames"]) / len(beep["frames"]) for i in range(3)]
                        loud = "LMR"[m.index(max(m))]
                        tag = f"event {count}" if is_none else f"beep {count}/{beeps}"
                        print(f"    {tag:<12} L {m[0]:6.2f}   M {m[1]:6.2f}   R {m[2]:6.2f}   loudest: {loud}")
                        if not is_none and count % 4 == 0 and count < beeps:
                            spot = SPOTS[(count // 4) % len(SPOTS)]
                            print(f"  >> MOVE the phone (still box {label}) to spot {count // 4 + 1}: {spot}. Hands out.")
                        if not is_none and count >= beeps:
                            done = True
                            break
                if frames == 0 and not warned and time.time() - start > 3:
                    warned = True
                    print("  No mic data yet. Is the Beacon turret firmware on the Pico (not an old test sketch)?")
        except KeyboardInterrupt:
            pass
    if lost:
        return count, True, path
    pico.write("MIC,0")
    what = "events" if is_none else "beeps"
    print(f"  Saved {count} {what} -> {os.path.relpath(path, ROOT)}")
    return count, False, path


def main():
    ap = argparse.ArgumentParser(description="Record labeled beeps for training")
    ap.add_argument("--session", required=True, type=int)
    ap.add_argument("--label", type=str.upper, choices=LABELS, help="record just one box; leave out to do all of them")
    ap.add_argument("--beeps", type=int, default=40, help="beeps per box (10 spots x 4)")
    ap.add_argument("--seconds", type=float, help="time limit per box (default 60 for NONE, 150 for boxes)")
    ap.add_argument("--port", help="serial port, found automatically if left out")
    ap.add_argument("--auto", action="store_true", help="no Enter prompts (when Claude runs it for you)")
    args = ap.parse_args()

    labels = [args.label] if args.label else LABELS
    pico = PicoSerial(args.port)
    if not args.label:
        print(f"Session {args.session}: A -> B -> C -> D -> E -> NONE. "
              f"Each box: press play once, {args.beeps // 4} spots inside THAT box, 4 beeps per spot. "
              "It stops by itself and tells you the next box.")

    i = 0
    while i < len(labels):
        label = labels[i]
        if args.auto:
            pass
        elif label == "NONE":
            input("\nNEXT: NONE (no beeps). PAUSE the beeper phone and put it away. Press Enter when ready... ")
        else:
            input(f"\nNEXT: BOX {label}. Hold the phone at box {label}'s opening, player open, NOT playing yet. "
                  "Press Enter when ready... ")
        count, lost, path = record_one(pico, label, args.session, args.beeps, args.seconds)
        if lost:
            print(f"\nLost the Pico mid-recording (USB cable?). Push the cable back in, then delete the partial file:\n"
                  f"  rm {os.path.relpath(path, ROOT)}\n"
                  f"and carry on with:  python3 tools/record.py --session {args.session} --label {label}")
            return
        if label != "NONE":
            print(f"  Box {label} done. PAUSE the phone.")
            if count < args.beeps and args.auto:
                print(f"  Only {count}/{args.beeps} beeps were heard.")
            elif count < args.beeps:
                ans = input(f"  Only {count}/{args.beeps} beeps were heard (volume at max? speaker toward the opening?). "
                            "Type r and Enter to redo this box, or just Enter to keep it: ").strip().lower()
                if ans == "r":
                    os.remove(path)
                    continue
        i += 1
    pico.close()
    if args.label:
        return
    if args.session == 1:
        print("\nSession 1 done! Take a 10-15 minute break and MOVE NOTHING. Then run:\n"
              "  python3 tools/record.py --session 2")
    else:
        print(f"\nSession {args.session} done! Tell Claude \"recorded\".")


if __name__ == "__main__":
    main()
