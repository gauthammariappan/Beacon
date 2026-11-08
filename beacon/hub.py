# Live state for the phone page, and a small web server for it (standard library only).
# live.py tells the hub what's happening; every open phone gets it instantly over Server-Sent Events.
import json
import os
import queue
import socket
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
    def __init__(self, racks, on_ack=None):
        self.lock = threading.Lock()
        self.subs = []
        self.on_ack = on_ack
        self.next_id = 1
        self.state = {"status": "standby", "racks": list(racks), "beeps": 0, "vote": 4,
                      "incidents": [], "started": time.time(), "message": ""}

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

    def no_beep(self, message):
        with self.lock:
            self.state.update(status="standby", beeps=0, message=message)
            self._emit("standby")

    def acknowledge(self, by):
        with self.lock:
            open_ones = [i for i in self.state["incidents"] if i["ack_t"] is None]
            if not open_ones:
                return False
            now = time.time()
            for inc in open_ones:
                inc["ack_t"] = now
                inc["ack_by"] = by
            self.state["status"] = "standby"
            self._emit("ack")
        if self.on_ack:
            self.on_ack()
        return True


def start_server(hub, port):
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

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                self._file("phone.html")
            elif path == "/qr":
                self._file("qr.html")
            elif path == "/state":
                self._send(200, json.dumps(hub.snapshot()), "application/json")
            elif path == "/info":
                self._send(200, json.dumps({"url": f"http://{lan_ip()}:{self.server.beacon_port}/"}), "application/json")
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
                            msg = q.get(timeout=15)
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
            if self.path.split("?")[0] != "/ack":
                self._send(404, "not found", "text/plain")
                return
            length = int(self.headers.get("Content-Length") or 0)
            try:
                by = json.loads(self.rfile.read(length) or b"{}").get("by") or "phone"
            except ValueError:
                by = "phone"
            self._send(200, json.dumps({"ok": hub.acknowledge(str(by)[:40])}), "application/json")

    class Server(ThreadingHTTPServer):
        allow_reuse_address = False   # fail loudly instead of sharing a port another app already uses
        daemon_threads = True

    last_error = None
    for p in range(port, port + 12):
        try:
            server = Server(("0.0.0.0", p), Handler)
        except OSError as e:
            last_error = e
            continue
        server.beacon_port = p
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server
    raise OSError(f"no free port between {port} and {port + 11}: {last_error}")
