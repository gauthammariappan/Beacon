# Live state for the phone page, and a small web server for it (standard library only).
# live.py (or remote.py) tells the hub what's happening; every open phone gets it instantly over
# Server-Sent Events. remote.py also passes a `control` object, which adds the /control remote.
import json
import os
import queue
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


def lan_ip():
    """The laptop's address on the local network (what a phone on the same Wi-Fi uses)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))   # nothing is sent; this only picks the outgoing interface
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class Hub:
    def __init__(self, racks, on_ack=None, idle_message=""):
        self.lock = threading.Lock()
        self.subs = []
        self.on_ack = on_ack
        self.next_id = 1
        # idle_message replaces the alert page's standby line ("Start listening from the Beacon laptop.")
        self.state = {"status": "standby", "racks": list(racks), "beeps": 0, "vote": 4,
                      "incidents": [], "started": time.time(), "message": idle_message}

    # ---- for the web server ----
    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.state))

    def subscribe(self):
        q = queue.Queue()
        with self.lock:
            self.subs.append(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.subs:
                self.subs.remove(q)

    def phones(self):
        """How many alert pages are open right now."""
        with self.lock:
            return len(self.subs)

    def get_incident(self, inc_id):
        with self.lock:
            for inc in self.state["incidents"]:
                if inc["id"] == inc_id:
                    return dict(inc)
        return None

    def is_open(self, inc_id):
        inc = self.get_incident(inc_id)
        return inc is not None and inc["ack_t"] is None

    def _emit(self, kind):
        # called with the lock held
        msg = json.dumps({"type": kind, "state": self.state})
        for q in self.subs:
            q.put(msg)

    # ---- for live.py ----
    def listening(self, vote):
        with self.lock:
            self.state.update(status="listening", beeps=0, vote=vote, message="")
            self._emit("listening")

    def beep(self, n):
        with self.lock:
            self.state["beeps"] = n
            self._emit("beep")

    def incident(self, rack, ranked, angle, beeps):
        with self.lock:
            inc = {"id": self.next_id, "rack": rack, "confidence": float(ranked[0][1]),
                   "runner_up": [ranked[1][0], float(ranked[1][1])] if len(ranked) > 1 else None,
                   "angle": float(angle), "beeps": int(beeps), "t": time.time(),
                   "ack_t": None, "ack_by": None}
            self.next_id += 1
            self.state["incidents"].insert(0, inc)
            self.state.update(status="alert", beeps=0)
            self._emit("incident")
            return inc["id"]

    def no_beep(self, message):
        with self.lock:
            self.state.update(status="standby", beeps=0, message=message)
            self._emit("standby")

    def acknowledge(self, by, upto=None):
        """Close the open alerts. With `upto`, only alerts up to that id (the one a phone was showing),
        so a press can't also close an alert that went out a moment later."""
        with self.lock:
            open_ones = [i for i in self.state["incidents"]
                         if i["ack_t"] is None and (upto is None or i["id"] <= upto)]
            if not open_ones:
                return False
            now = time.time()
            for inc in open_ones:
                inc["ack_t"] = now
                inc["ack_by"] = by
            if not any(i["ack_t"] is None for i in self.state["incidents"]):
                self.state["status"] = "standby"
            self._emit("ack")
        if self.on_ack:
            try:
                self.on_ack()
            except Exception as e:   # e.g. the Pico got unplugged; the alert is closed either way
                print(f"(Couldn't turn the laser off: {e})")
        return True


def start_server(hub, port, control=None):
    """Serves the alert page. With `control` (remote.py's turret) it also serves the /control remote."""
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, body, ctype):
            data = body.encode() if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _file(self, name):
            with open(os.path.join(WEB_DIR, name), encoding="utf-8") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")

        def _json(self, obj):
            self._send(200, json.dumps(obj), "application/json")

        def _body(self):
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return {}
            return body if isinstance(body, dict) else {}

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                self._file("phone.html")
            elif path == "/qr":
                self._file("qr.html")
            elif path == "/state":
                self._json(hub.snapshot())
            elif path == "/info":
                base = f"http://{lan_ip()}:{self.server.beacon_port}/"
                self._json({"url": base, "control_url": base + "control" if control else None})
            elif control and path == "/control":
                self._file("control.html")
            elif control and path == "/control/state":
                self._json(control.snapshot())
            elif path == "/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                q = hub.subscribe()
                try:
                    hello = json.dumps({"type": "hello", "state": hub.snapshot()})
                    self.wfile.write(f"data: {hello}\n\n".encode())
                    self.wfile.flush()
                    while True:
                        try:
                            msg = q.get(timeout=5)
                        except queue.Empty:
                            self.wfile.write(b": still here\n\n")   # keeps phones from dropping the stream
                            self.wfile.flush()
                            continue
                        self.wfile.write(f"data: {msg}\n\n".encode())
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    hub.unsubscribe(q)
            else:
                self._send(404, "not found", "text/plain")

        def do_POST(self):
            path = self.path.split("?")[0]
            body = self._body()
            if path == "/ack":
                by = str(body.get("by") or "phone").strip()[:40] or "phone"
                upto = body.get("id")
                if not isinstance(upto, int) or isinstance(upto, bool):
                    upto = None
                self._json({"ok": hub.acknowledge(by, upto)})
            elif control and path == "/control/aim":
                rack = str(body.get("rack") or "").strip().upper()
                if rack not in control.angles:
                    self._send(400, "unknown rack", "text/plain")
                else:
                    self._json(control.aim(rack))
            elif control and path == "/control/off":
                self._json(control.laser_off())
            elif control and path == "/control/home":
                self._json(control.center())
            else:
                self._send(404, "not found", "text/plain")

    class Server(ThreadingHTTPServer):
        # Reusing the address lets a restart get the same port straight away, even while the last
        # run's closed connections are still winding down; otherwise phones left on :8787 are stranded.
        # taken() below makes sure we never share a port another app is actually listening on.
        allow_reuse_address = True
        daemon_threads = True

        def handle_error(self, request, client_address):
            # phones drop connections all the time (screen lock, Wi-Fi blips); no traceback for that
            if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError,
                                              ConnectionAbortedError, TimeoutError)):
                return
            super().handle_error(request, client_address)

    def taken(p):
        for host in {"127.0.0.1", lan_ip()}:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.settimeout(0.3)
                if probe.connect_ex((host, p)) == 0:
                    return True
        return False

    last_error = None
    for p in range(port, port + 12):
        if taken(p):
            last_error = f"something else is listening on {p}"
            continue
        try:
            server = Server(("0.0.0.0", p), Handler)
        except OSError as e:
            last_error = e
            continue
        server.beacon_port = p
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server
    raise OSError(f"no free port between {port} and {port + 11}: {last_error}")
