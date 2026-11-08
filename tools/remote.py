#!/usr/bin/env python3
"""Beacon with a phone remote in place of the microphones and the model.

  python3 tools/remote.py

The laptop serves two pages:
  /          the alert page, the same one live.py serves
  /control   the remote: tap a rack, the laser points at it, then the alert goes out

"Mark as Checked" on the alert page turns the laser off, same as with live.py. Nothing here
listens to the mics, so the alert page stays on standby until the remote picks a rack.
For the real pipeline (mics + model), run tools/live.py instead.

Angles come from config/aim_points.json (A 119, B 99, C 68, D 40, E 23).
"""
import argparse
import json
import os
import signal
import sys
import threading
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
from beacon.hub import Hub, lan_ip, start_server                 # noqa: E402
from beacon.serial_port import PicoSerial, PortBusy, find_port  # noqa: E402

RACKS = ["A", "B", "C", "D", "E"]
DEFAULT_ANGLES = {"A": 119.0, "B": 99.0, "C": 68.0, "D": 40.0, "E": 23.0}
OPERATOR = "Operator"   # the name in the history when the remote turns the laser off
SAME_DEG = 0.3          # closer than this counts as already there (the Pico reports tenths of a degree)

_print_lock = threading.Lock()


def log(msg):
    with _print_lock:
        try:
            print(time.strftime("%H:%M:%S  ") + msg, flush=True)
        except OSError:      # the Terminal window is gone; carry on (we may be turning the laser off)
            pass


def load_angles():
    try:
        with open(os.path.join(ROOT, "config", "aim_points.json")) as f:
            saved = {k: float(v) for k, v in json.load(f).items()}
    except (OSError, ValueError):
        saved = {}
    return {r: saved.get(r, DEFAULT_ANGLES[r]) for r in RACKS}


def _deg(reply):
    try:
        return float(reply.split(",")[1])
    except (AttributeError, IndexError, ValueError):
        raise ConnectionError(f"garbled reply {reply!r}")


class PicoError(Exception):
    """The Pico answered with ERR,..."""


class Turret:
    """Owns the Pico. The pages only change self.goal, and one thread moves the turret to match it.

    That thread always works toward the newest goal, so quick taps never pile up: tap B and then D,
    and it finishes the move it's in and goes to D. The laser is off whenever the turret moves.
    It comes back on, and the alert goes out, only once the turret has arrived.
    """

    def __init__(self, hub, angles, port=None, opener=PicoSerial):
        self.hub = hub
        self.angles = dict(angles)
        self.port = port
        self.opener = opener                # the tests hand in a pretend Pico here
        self.cv = threading.Condition()     # an RLock underneath; guards everything below
        self.goal = {"kind": "idle", "rack": None, "incident": None}
        self.pico = None
        self.angle = None                   # where the servo is, as far as we know
        self.laser = False
        self.home = None
        self.error = ""
        self.working = False
        self.stopping = False
        self.thread = threading.Thread(target=self._run, name="turret", daemon=True)

    # ---- called by the web pages, from any thread ----

    def aim(self, rack):
        with self.cv:
            if self.pico is None:
                return self._snapshot()
            g = self.goal
            if g["kind"] == "rack" and g["rack"] == rack and (g["incident"] is None or self.hub.is_open(g["incident"])):
                return self._snapshot()     # already on its way there, or already on it
            self._close_alert(g)            # the laser is leaving that rack, so its alert ends here
            self.goal = {"kind": "rack", "rack": rack, "incident": None}
            self.error = ""
            self.cv.notify_all()
            log(f"Remote: rack {rack}")
            return self._snapshot()

    def laser_off(self):
        with self.cv:
            # Closing the alert is what turns the laser off (see _plan). Doing it while holding the
            # lock means an alert can't slip out between the check and the goal change.
            self.hub.acknowledge(OPERATOR)
            g = self.goal
            if not (g["kind"] == "rack" and g["incident"] is not None):
                self.goal = {"kind": "off", "rack": None, "incident": None}   # cancels a move in progress
            self.error = ""
            self.cv.notify_all()
            log("Remote: laser off")
            return self._snapshot()

    def center(self):
        with self.cv:
            self.hub.acknowledge(OPERATOR)
            self.goal = {"kind": "home", "rack": None, "incident": None}
            self.error = ""
            self.cv.notify_all()
            log("Remote: center")
            return self._snapshot()

    def _close_alert(self, g):
        # called with the lock held
        if g["kind"] == "rack" and g["incident"] is not None and self.hub.is_open(g["incident"]):
            self.hub.acknowledge(OPERATOR, upto=g["incident"])

    def poke(self):
        """Something was marked as checked on the alert page. Look again right away."""
        with self.cv:
            self.cv.notify_all()

    def snapshot(self):
        with self.cv:
            return self._snapshot()

    def _snapshot(self):
        g = self.goal
        inc = self.hub.get_incident(g["incident"]) if g["incident"] is not None else None
        busy = self.pico is not None and (self.working or self._plan() is not None)
        if self.pico is None:
            phase = "offline"
        elif g["kind"] == "rack":
            if inc is not None and inc["ack_t"] is not None:
                phase = "checked"
            else:                           # "on" only once the laser really is (not while re-aiming)
                phase = "on" if inc is not None and self.laser else "aiming"
        elif g["kind"] == "home":
            phase = "centering" if busy else "home"
        else:
            phase = g["kind"]               # "off" or "idle"
        pointing = None
        if self.angle is not None:
            pointing = next((r for r, a in self.angles.items() if abs(self.angle - a) < 0.5), None)
        return {"connected": self.pico is not None, "error": self.error, "phase": phase, "rack": g["rack"],
                "alert": inc and {"t": inc["t"], "ack_t": inc["ack_t"], "ack_by": inc["ack_by"]},
                "angle": self.angle, "laser": bool(self.laser), "pointing": pointing, "busy": busy,
                "angles": self.angles, "phones": self.hub.phones(), "now": time.time(),
                "seq": time.monotonic()}    # lets the page drop answers that arrive out of order

    # ---- deciding what to do ----

    def _plan(self):
        """The next thing to send so the turret matches the goal, or None if it already does."""
        g = self.goal
        target, want_laser, why = None, False, None
        if g["kind"] == "rack":
            if g["incident"] is None or self.hub.is_open(g["incident"]):
                target, want_laser = self.angles[g["rack"]], True
            else:
                why = "checked"             # someone checked it: laser off, stay put
        elif g["kind"] == "home":
            target, why = self.home, "home"
        elif g["kind"] == "off":
            why = "off"
        move = target is not None and (self.angle is None or abs(self.angle - target) > SAME_DEG)
        if self.laser and (move or not want_laser):
            return ("LASER,0", "OK,LASER", None if move else why)
        if move:
            if g["kind"] == "home":
                return ("HOME", "POS,", "home")
            return (f"AIM,{target:g}", "POS,", None)
        if want_laser and not self.laser:
            return ("LASER,1", "OK,LASER", None)
        if want_laser and g["incident"] is None:
            return ("alert", None, None)
        return None

    def _raise_alert(self):
        # called with the lock held, so the goal can't change halfway through
        rack = self.goal["rack"]
        self.goal["incident"] = self.hub.incident(rack, [(rack, 1.0)], self.angles[rack], 0)
        log(f"Rack {rack}: laser on at {self.angles[rack]:g}°, alert sent")

    # ---- the turret thread ----

    def start(self):
        self.thread.start()

    def stop(self):
        with self.cv:
            self.stopping = True
            self.cv.notify_all()
        if self.thread.is_alive():
            self.thread.join(timeout=5)
        elif self.pico is not None:
            self._shutdown()

    def connect_first(self):
        """Connect before the pages go up. Exits if another program already has the Pico."""
        return self._connect(startup=True)

    def _run(self):
        while not self.stopping:
            if self.pico is None:
                if not self._connect():
                    self._pause(1.5)
                continue
            try:
                step = self._next_step()
                if step is None:
                    self._check_pico()
                else:
                    self._do(step)
            except PicoError as e:
                with self.cv:
                    self._close_alert(self.goal)
                    self.error = f"The Pico refused that ({e}). Check config/aim_points.json."
                    self.goal = {"kind": "off", "rack": None, "incident": None}
                    self.working = False
                log(self.error)
            except ConnectionError as e:
                self._lost(e)
            except Exception as e:          # a bug shouldn't leave the remote dead; start over
                log(f"Unexpected error: {e!r}")
                self._lost(e)
                self._pause(1.0)
        self._shutdown()

    def _pause(self, seconds):
        with self.cv:
            if not self.stopping:
                self.cv.wait(seconds)

    def _next_step(self):
        """The next serial command to send, or None after waiting a moment with nothing to do."""
        with self.cv:
            while True:
                step = self._plan()
                if step is not None and step[0] == "alert":
                    self._raise_alert()
                    continue
                if step is None:
                    self.working = False
                    if not self.stopping:
                        self.cv.wait(0.25)  # a tap or a check wakes this early
                    return None
                self.working = True
                return step

    def _do(self, step):
        cmd, expect, why = step
        reply = self._send(cmd, expect)
        with self.cv:
            if cmd.startswith("LASER,"):
                self.laser = cmd.endswith("1")
            elif cmd == "HOME":
                self.angle, self.laser = _deg(reply), False
            else:
                self.angle = float(cmd.split(",")[1])   # AIM lands exactly on what it was sent
            self.working = False
            g = self.goal
            inc = self.hub.get_incident(g["incident"]) if why == "checked" and g["incident"] is not None else None
        if inc:
            log(f"Rack {g['rack']} checked by {inc['ack_by']}. Laser off.")
        elif why == "off":
            log("Laser off.")
        elif why == "home":
            log(f"Centered at {self.angle:g}°. Laser off.")

    def _send(self, cmd, expect, timeout=5.0, connecting=False, pico=None):
        """Send one command and return the reply that starts with `expect`."""
        p = pico or self.pico
        for _ in range(20):                 # throw away anything nobody asked for
            stale = p.lines(0)
            if not stale:
                break
            if "READY" in stale and not connecting:
                raise ConnectionError("the Pico restarted")
        p.write(cmd)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for line in p.lines(0.1):
                if line.startswith(expect):
                    return line
                if line.startswith("ERR"):
                    raise PicoError(f"{cmd} got {line}")
                if line == "READY" and not connecting:
                    raise ConnectionError("the Pico restarted")
        raise ConnectionError(f"no answer to {cmd}")

    def _check_pico(self):
        port = getattr(self.pico, "port", None)
        if port and port.startswith("/dev/") and not os.path.exists(port):
            raise ConnectionError("it was unplugged")
        if "READY" in self.pico.lines(0):   # it restarted by itself: back at center, laser off
            raise ConnectionError("the Pico restarted")

    def _connect(self, startup=False):
        port = self.port or find_port()
        if not port or (port.startswith("/dev/") and not os.path.exists(port)):
            self._set_error("Can't find the Pico. Plug it into the laptop; it connects by itself.")
            return False
        try:
            pico = self.opener(port)
        except PortBusy as e:
            if startup:
                raise
            self._set_error(str(e))
            return False
        except (SystemExit, OSError) as e:  # PicoSerial explains problems by exiting
            self._set_error(str(e) or f"Can't open {port}.")
            return False
        try:
            self._send("MIC,0", "OK,MIC", 3, connecting=True, pico=pico)     # in case live.py left the mics on
            self._send("LASER,0", "OK,LASER", 3, connecting=True, pico=pico)
            home = _deg(self._send("HOME?", "HOME,", 3, connecting=True, pico=pico))
            angle = _deg(self._send("POS?", "POS,", 3, connecting=True, pico=pico))
        except (ConnectionError, PicoError):
            try:
                pico.close()
            except OSError:
                pass
            self._set_error("The Pico isn't answering. Is the turret firmware (beacon_turret.ino) on it?")
            return False
        with self.cv:
            # only now does it count as connected, so a tap can't slip in halfway through the handshake
            self.pico, self.home, self.angle, self.laser, self.error = pico, home, angle, False, ""
            self.cv.notify_all()
        log(f"Pico connected on {port}. Turret at {angle:g}°, laser off.")
        return True

    def _lost(self, why):
        pico = self.pico
        with self.cv:
            self.pico = None
            self.angle = None
            self.laser = False
            self.working = False
            g = self.goal
            # A tap that hadn't lit anything yet shouldn't fire whenever the Pico comes back, maybe
            # minutes later. An alert that's still open does get its laser back.
            if g["kind"] == "home" or (g["kind"] == "rack" and g["incident"] is None):
                self.goal = {"kind": "idle", "rack": None, "incident": None}
        if pico is not None:
            try:
                pico.close()
            except OSError:
                pass
        self._set_error(f"Lost the Pico ({why}). Reconnecting…")

    def _set_error(self, msg):
        with self.cv:
            changed = msg != self.error
            self.error = msg
        if changed:
            log(msg)

    def _shutdown(self):
        pico, self.pico = self.pico, None
        if pico is None:
            return
        try:
            self._send("LASER,0", "OK,LASER", 1.0, connecting=True, pico=pico)   # wait until it's really off
        except (ConnectionError, PicoError, OSError):
            pass
        try:
            pico.close()
        except OSError:
            pass


def _stop_on_signal(signum, frame):
    raise KeyboardInterrupt


def main():
    # closing the Terminal window (SIGHUP) or a plain kill (SIGTERM) shuts down like Ctrl+C: laser off
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, _stop_on_signal)
    ap = argparse.ArgumentParser(description="Point the Beacon laser from a phone (no mics, no model)")
    ap.add_argument("--port", help="the Pico's serial port (found automatically)")
    ap.add_argument("--web-port", type=int, default=8787, help="port for the pages (the next free one is used if it's taken)")
    args = ap.parse_args()

    angles = load_angles()
    hub = Hub(RACKS, idle_message="Waiting for the next alert.")
    turret = Turret(hub, angles, port=args.port)
    hub.on_ack = turret.poke
    print("Beacon remote: no microphones, no model.   Laser angles: " + "  ".join(f"{r} {angles[r]:g}" for r in RACKS))
    if not turret.connect_first():
        print("Waiting for the Pico. Plug it in and it connects by itself.")
    try:
        web = start_server(hub, args.web_port, control=turret)
    except OSError as e:
        turret.stop()
        raise SystemExit(f"Couldn't start the pages: {e}")

    ip, p = lan_ip(), web.beacon_port
    print(f"\n  Alert page (technician's phone):  http://{ip}:{p}/")
    print(f"  Remote (operator's phone):        http://{ip}:{p}/control")
    print(f"  QR codes on this laptop:          http://localhost:{p}/qr   and   http://localhost:{p}/qr?control")
    print("\nBoth phones need to be on the same Wi-Fi or hotspot as this laptop. Ctrl+C stops it (laser off).\n")
    turret.start()
    try:
        while turret.thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)   # a second Ctrl+C mustn't cut the cleanup short
        turret.stop()
        log("Stopped. Laser off.")


if __name__ == "__main__":
    main()
