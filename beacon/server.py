"""FastAPI backend server for Beacon v2.1 acoustic localization."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import csv
import glob
import json
import os
from pathlib import Path
import socket
import time
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from beacon.features import extract_spatial_features
from beacon.incidents import Incident, IncidentManager, IncidentState
from beacon.location_model import LocationClassifier
from beacon.signal import SignalProcessor

# Spatial acoustic share profiles for 5 racks (A-E)
RACK_PROFILES: dict[str, list[float]] = {
    "A": [0.65, 0.25, 0.10],
    "B": [0.46, 0.46, 0.08],
    "C": [0.22, 0.56, 0.22],
    "D": [0.08, 0.46, 0.46],
    "E": [0.10, 0.25, 0.65],
}

# Default layout matching physical aisle layout in ARCHITECTURE.md
DEFAULT_LAYOUT = {
    "aisle_length_cm": 85.0,
    "racks": [
        {"id": "A", "x_cm": 0.0, "width_cm": 15.0},
        {"id": "B", "x_cm": 20.0, "width_cm": 15.0},
        {"id": "C", "x_cm": 40.0, "width_cm": 15.0},
        {"id": "D", "x_cm": 60.0, "width_cm": 15.0},
        {"id": "E", "x_cm": 80.0, "width_cm": 15.0},
    ],
    "microphones": [
        {"id": "L", "in_front_of": "A", "x_cm": 0.0, "y_cm": 15.0},
        {"id": "M", "in_front_of": "C", "x_cm": 40.0, "y_cm": 15.0},
        {"id": "R", "in_front_of": "E", "x_cm": 80.0, "y_cm": 15.0},
    ],
}

# Global backend components
signal_processor = SignalProcessor(alpha=0.02, initial_noise_floor=[10.0, 10.0, 10.0])
location_classifier = LocationClassifier()
incident_manager = IncidentManager(silence_timeout_s=10.0)

current_mic_levels: dict[str, float] = {"L": 10.0, "M": 10.0, "R": 10.0}
active_websockets: set[WebSocket] = set()
replay_paused: bool = True

# AimController & Serial hardware state
serial_connection: Any = None
last_aimed_rack: Optional[str] = None
laser_off_task: Optional[asyncio.Task] = None


def send_serial_command(command: str) -> None:
    """Send command to physical Pico over serial, or log in replay/simulation mode."""
    global serial_connection
    cmd_str = command.strip() + "\n"
    if serial_connection is not None and getattr(serial_connection, "is_open", False):
        try:
            serial_connection.write(cmd_str.encode("utf-8"))
            serial_connection.flush()
            print(f"[Serial TX] -> Pico: {command.strip()}")
            return
        except Exception as e:
            print(f"[Serial TX] Serial write failed ({e}). Falling back to simulation log.")

    # Replay / Simulation mode logging
    print(f"[AimController TX] {command.strip()}")


def load_aim_points() -> dict[str, float]:
    """Load saved servo pan angles from config/aim_points.json, aim_points.json, or defaults."""
    candidates = [
        Path("config/aim_points.json"),
        Path("aim_points.json"),
    ]
    for path in candidates:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    points: dict[str, float] = {}
                    for k, v in data.items():
                        if isinstance(v, (int, float)):
                            points[k.upper()] = float(v)
                        elif isinstance(v, dict) and "pan" in v:
                            points[k.upper()] = float(v["pan"])
                    if points:
                        return points
            except Exception as e:
                print(f"[AimController] Error reading {path}: {e}")

    # Fallback pan angles (SG90 servo degrees: 90 is center)
    return {"A": 35.0, "B": 62.0, "C": 90.0, "D": 118.0, "E": 145.0}


async def aim_turret_at_rack(rack: str) -> None:
    """Aim physical laser turret at predicted rack, enable laser, and trigger blanking."""
    global laser_off_task, last_aimed_rack
    points = load_aim_points()
    pan_angle = points.get(rack.upper(), 90.0)

    # a. Lookup pan angle and send AIM,<pan>\n and LASER,1\n
    send_serial_command(f"AIM,{round(pan_angle, 1)}")
    send_serial_command("LASER,1")

    # b. Call signal_processor.trigger_blanking(350) to initiate 350ms microphone ignore-window
    signal_processor.trigger_blanking(350)

    last_aimed_rack = rack.upper()

    # c. Spawn async timer (asyncio.create_task) that sleeps 5.0 seconds, then sends LASER,0\n
    if laser_off_task is not None and not laser_off_task.done():
        laser_off_task.cancel()

    async def _turn_off_laser():
        try:
            await asyncio.sleep(5.0)
            send_serial_command("LASER,0")
        except asyncio.CancelledError:
            pass

    laser_off_task = asyncio.create_task(_turn_off_laser())



def generate_demo_frames(rack: str, pattern: str) -> list[str]:
    """Generate a realistic 4-second sequence of 50 Hz frames matching rack spatial profile and alarm pattern."""
    rack_key = rack.upper()
    pattern_key = pattern.upper()
    shares = RACK_PROFILES.get(rack_key, [0.33, 0.34, 0.33])

    lines: list[str] = []
    base_ms = int(time.time() * 1000)

    for i in range(200):  # 200 frames at 20 ms = 4.0 seconds
        ms = base_ms + i * 20
        is_active = False

        if pattern_key == "P1":
            # P1: Pulses separated by standard >1.0s gap ("UPS On Battery")
            # Beep 1: frames 5..10 (120 ms), Beep 2: frames 70..75 (120 ms), Beep 3: frames 135..140 (120 ms)
            if (5 <= i <= 10) or (70 <= i <= 75) or (135 <= i <= 140):
                is_active = True
        elif pattern_key == "P2":
            # P2: Continuous rapid beeping with <1.0s gap ("UPS Low Battery")
            # 4 frames active (80 ms), 6 frames quiet (120 ms) -> 200 ms period
            if i >= 5 and ((i - 5) % 10) < 4:
                is_active = True
        elif pattern_key == "P3":
            # P3: Continuous steady tone > 600 ms ("UPS Overload")
            # 40 frames active = 800 ms unbroken tone
            if 5 <= i <= 44:
                is_active = True

        if is_active:
            total_energy = 280.0
            l25 = round(total_energy * shares[0], 1)
            m25 = round(total_energy * shares[1], 1)
            r25 = round(total_energy * shares[2], 1)
            line = f"E,{ms},{l25},{m25},{r25},10.0,10.0,10.0,10.0,10.0,10.0"
        else:
            line = f"E,{ms},10.0,10.0,10.0,10.0,10.0,10.0,10.0,10.0,10.0"

        lines.append(line)

    return lines



async def broadcast_json(message: dict[str, Any]) -> None:
    """Broadcast JSON payload to all active WebSocket clients."""
    if not active_websockets:
        return
    dead: list[WebSocket] = []
    for ws in list(active_websockets):
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        active_websockets.discard(ws)


async def broadcast_incident(incident: Incident) -> None:
    """Instantly push incident state update to all WebSocket clients."""
    data = incident.to_dict()
    payload = {
        "type": "incident",
        **data,
    }
    await broadcast_json(payload)


async def run_10hz_stream() -> None:
    """Stream mic levels at 10 Hz and check for incident silence timeout."""
    while True:
        try:
            # 1. 10 Hz mic levels broadcast
            payload = {
                "type": "mic_levels",
                "L": round(current_mic_levels["L"], 2),
                "M": round(current_mic_levels["M"], 2),
                "R": round(current_mic_levels["R"], 2),
            }
            await broadcast_json(payload)

            # 2. Check for 10 s silence timeout on active incident
            cleared_incident = incident_manager.check_timeout()
            if cleared_incident is not None:
                await broadcast_incident(cleared_incident)

            await asyncio.sleep(0.1)  # 10 Hz
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(0.1)


def find_pico_serial_port() -> Optional[str]:
    """Find live Raspberry Pi Pico USB CDC serial port."""
    serial_port = os.getenv("SERIAL_PORT")
    if serial_port and os.path.exists(serial_port):
        return serial_port
    matches = (
        glob.glob("/dev/cu.usbmodem*")
        + glob.glob("/dev/tty.usbmodem*")
        + glob.glob("/dev/ttyACM*")
        + glob.glob("/dev/ttyUSB*")
    )
    return matches[0] if matches else None


async def run_serial_reader() -> None:
    """Layer 2 ingest loop: strictly listens to live Raspberry Pi Pico serial port (115200 baud).

    Replay of recorded CSV is paused by default (replay_paused = True) and no synthetic CSV
    or synthetic frames are generated.
    """
    global serial_connection, replay_paused
    loop = asyncio.get_running_loop()

    while True:
        try:
            # 1. Connect or re-connect to live Raspberry Pi Pico if not already open
            if serial_connection is None or not getattr(serial_connection, "is_open", False):
                port = find_pico_serial_port()
                if port:
                    try:
                        import serial
                        ser = serial.Serial(port, baudrate=115200, timeout=0.1)
                        ser.reset_input_buffer()
                        serial_connection = ser
                        print(f"[Serial] Connected to hardware Pico on {port} (115200 baud)")
                    except Exception as e:
                        serial_connection = None
                        print(f"[Serial] Could not open {port}: {e}")

            # 2. If physical Pico is connected, stream incoming live hardware frames
            if serial_connection is not None and getattr(serial_connection, "is_open", False):
                try:
                    raw_line = await loop.run_in_executor(None, serial_connection.readline)
                    if not raw_line:
                        await asyncio.sleep(0.005)
                        continue
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or not line.startswith("E,"):
                        continue
                    await handle_serial_line(line)
                    continue
                except Exception as e:
                    print(f"[Serial] Hardware read error: {e}. Closing and retrying...")
                    try:
                        serial_connection.close()
                    except Exception:
                        pass
                    serial_connection = None
                    await asyncio.sleep(0.5)
                    continue

            # 3. No hardware Pico connected
            if replay_paused:
                # Idle wait: check for hardware reconnection every 500 ms without replay
                await asyncio.sleep(0.5)
                continue

            # 4. If replay was explicitly unpaused via API and no Pico hardware is present:
            # Replay strictly from recorded dataset (never generate synthetic frames)
            test_csv_path = Path("recordings/session2_test.csv")
            if test_csv_path.exists():
                with open(test_csv_path, mode="r", encoding="utf-8") as f:
                    reader = csv.reader(f)
                    for row in reader:
                        if replay_paused or (serial_connection is not None and getattr(serial_connection, "is_open", False)):
                            break
                        if not row:
                            continue
                        line = ""
                        for c in row:
                            c = c.strip()
                            if c.startswith("E,"):
                                line = c
                                break
                        if not line and len(row) >= 11 and row[0].strip().upper() == "E":
                            line = ",".join(c.strip() for c in row)

                        if line:
                            await handle_serial_line(line)
                            await asyncio.sleep(0.02)  # 50 Hz frame rate = 20 ms
            else:
                await asyncio.sleep(0.5)

        except asyncio.CancelledError:
            if serial_connection is not None:
                try:
                    serial_connection.close()
                except Exception:
                    pass
                serial_connection = None
            break
        except Exception:
            await asyncio.sleep(0.5)


async def handle_serial_line(line: str) -> None:
    """Process a single 50 Hz serial line through the Beacon pipeline."""
    # Update latest live mic levels for 10 Hz WebSocket streaming
    tokens = line.split(",")
    if len(tokens) >= 5 and tokens[0].upper() == "E":
        try:
            current_mic_levels["L"] = float(tokens[2])
            current_mic_levels["M"] = float(tokens[3])
            current_mic_levels["R"] = float(tokens[4])
        except (ValueError, TypeError):
            pass

    # Feed frame to SignalProcessor (Layer 3)
    event = signal_processor.process_line(line)
    if event is not None:
        # Check previous state before feeding new event
        prev_incident = incident_manager.get_active_incident()
        prev_state = prev_incident.state if prev_incident else None

        # Brain 1: Spatial Location Classifier (Layer 4)
        loc_res = location_classifier.predict(event.features, update_vote=True)

        # Brain 2 (Cadence Tracker) & Action: Incident Manager State Machine (Layer 5)
        incident = incident_manager.feed_beep(
            location_result=loc_res,
            event=event,
        )

        if incident is not None:
            # Aim laser turret when incident transitions to LOCATED or rack changes
            if incident.rack in ["A", "B", "C", "D", "E"] and incident.state != IncidentState.CLEARED:
                should_aim = False
                if incident.state == IncidentState.LOCATED and prev_state != IncidentState.LOCATED:
                    should_aim = True
                elif incident.rack != last_aimed_rack:
                    should_aim = True

                if should_aim:
                    await aim_turret_at_rack(incident.rack)

            # Instantly push incident state change to all WebSocket clients
            await broadcast_incident(incident)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage background asyncio tasks for serial reader and 10 Hz WebSocket streaming."""
    stream_task = asyncio.create_task(run_10hz_stream())
    serial_task = asyncio.create_task(run_serial_reader())
    yield
    stream_task.cancel()
    serial_task.cancel()
    if laser_off_task and not laser_off_task.done():
        laser_off_task.cancel()
    try:
        await asyncio.gather(stream_task, serial_task, return_exceptions=True)
    except Exception:
        pass


app = FastAPI(
    title="Beacon v2.1 Backend",
    description="Acoustic localization API and WebSocket live stream.",
    version="2.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.websocket("/live")
async def websocket_live(websocket: WebSocket) -> None:
    """WebSocket endpoint streaming 10 Hz mic levels and pushing incident state changes instantly."""
    await websocket.accept()
    active_websockets.add(websocket)

    # Immediately push current mic levels and active incident if one exists
    try:
        await websocket.send_json({
            "type": "mic_levels",
            "L": round(current_mic_levels["L"], 2),
            "M": round(current_mic_levels["M"], 2),
            "R": round(current_mic_levels["R"], 2),
        })
        active_inc = incident_manager.get_active_incident()
        if active_inc is not None:
            await websocket.send_json({
                "type": "incident",
                **active_inc.to_dict(),
            })
    except Exception:
        pass

    try:
        while True:
            # Keep connection open and receive optional client messages
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        active_websockets.discard(websocket)


def get_local_ip() -> str:
    """Detect LAN IP for mobile pager QR code handoff."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


@app.get("/layout")
def get_layout() -> dict[str, Any]:
    """Return physical rack and microphone positions."""
    layout_data = dict(DEFAULT_LAYOUT)
    layout_path = Path("rack_layout.json")
    if layout_path.exists():
        try:
            with open(layout_path, "r", encoding="utf-8") as f:
                layout_data = json.load(f)
        except Exception:
            pass
    layout_data["local_ip"] = get_local_ip()
    return layout_data


@app.post("/incidents/{incident_id}/ack")
async def acknowledge_incident(incident_id: str) -> dict[str, Any]:
    """Acknowledge an incident and flip its state to ACKNOWLEDGED."""
    incident = incident_manager.acknowledge(incident_id)
    if incident is None:
        raise HTTPException(
            status_code=404,
            detail=f"Incident with id '{incident_id}' not found.",
        )

    # Push state change instantly to WebSocket clients
    await broadcast_incident(incident)
    return incident.to_dict()


@app.get("/model/location/metrics")
@app.get("/model/metrics")
def get_location_metrics() -> dict[str, Any]:
    """Serve location model evaluation metrics and confusion matrices."""
    metrics_path = Path("artifacts/location_metrics.json")
    if not metrics_path.exists():
        return {
            "classes": ["A", "B", "C", "D", "E", "NONE"],
            "loudest_mic": {"accuracy": 0.0, "confusion_matrix": []},
            "weighted_centroid": {"accuracy": 0.0, "confusion_matrix": []},
            "random_forest": {"accuracy": 0.0, "confusion_matrix": []},
            "placeholder": True,
        }
    with open(metrics_path, "r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/model/rhythm/metrics")
def get_rhythm_metrics() -> dict[str, Any]:
    """Serve teammate's temporal rhythm model (Brain 2) metrics."""
    metrics_path = Path("beep_model/artifacts/metrics.json")
    if not metrics_path.exists():
        return {
            "model_name": "random_forest",
            "val_macro_f1": {"sgd_log": 0.0, "random_forest": 0.0},
            "test": {
                "accuracy": 0.0,
                "macro_f1": 0.0,
                "confusion_matrix": {"labels": [], "rows_are_true": []},
            },
            "placeholder": True,
        }
    try:
        with open(metrics_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {
            "error": str(e),
            "val_macro_f1": {"sgd_log": 0.0, "random_forest": 0.0},
            "test": {
                "accuracy": 0.0,
                "macro_f1": 0.0,
                "confusion_matrix": {"labels": [], "rows_are_true": []},
            },
            "placeholder": True,
        }


@app.get("/incidents")
def get_incidents() -> dict[str, Any]:
    """Return current active incident and historical incidents."""
    active = incident_manager.get_active_incident()
    return {
        "active": active.to_dict() if active is not None else None,
        "history": incident_manager.get_history(),
    }


@app.post("/demo/replay/toggle")
def toggle_replay(payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Pause or resume the automatic CSV replay simulator loop."""
    global replay_paused
    if payload and "paused" in payload:
        replay_paused = bool(payload["paused"])
    else:
        replay_paused = not replay_paused
    return {"replay_paused": replay_paused}


@app.post("/demo/trigger/{rack}/{pattern}")
async def demo_trigger(rack: str, pattern: str, realtime: bool = False) -> dict[str, Any]:
    """Trigger a realistic 4-second acoustic sequence for demoing in a pitch.

    Automatically pauses background random replay to prevent collision.
    """
    global replay_paused
    replay_paused = True

    rack_upper = rack.upper()
    pattern_upper = pattern.upper()
    if rack_upper not in RACK_PROFILES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid rack '{rack}'. Must be one of {list(RACK_PROFILES.keys())}.",
        )
    if pattern_upper not in ["P1", "P2", "P3"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid pattern '{pattern}'. Must be one of P1, P2, or P3.",
        )

    # Clean in-progress runs so this demo sequence begins deterministically
    signal_processor.reset()
    location_classifier.reset()
    incident_manager.reset()
    global last_aimed_rack
    last_aimed_rack = None

    lines = generate_demo_frames(rack_upper, pattern_upper)

    for line in lines:
        await handle_serial_line(line)
        if realtime:
            await asyncio.sleep(0.02)  # 50 Hz interval

    active_inc = incident_manager.get_active_incident()
    return {
        "status": "triggered",
        "rack": rack_upper,
        "pattern": pattern_upper,
        "replay_paused": replay_paused,
        "incident": active_inc.to_dict() if active_inc else None,
    }


@app.get("/")
def get_root(request: Request) -> Any:
    """Health check for API clients, or serve the NOC Dashboard if requested via browser."""
    accept = request.headers.get("accept", "")
    index_file = Path("web/index.html")
    if "text/html" in accept and index_file.exists():
        return FileResponse(index_file)
    return {
        "system": "Beacon v2.1 Backend",
        "status": "online",
        "active_incident": bool(incident_manager.get_active_incident()),
        "local_ip": get_local_ip(),
    }


@app.get("/dashboard")
def get_dashboard() -> Any:
    """Explicit endpoint to serve the Beacon v2.1 frontend dashboard."""
    index_file = Path("web/index.html")
    if index_file.exists():
        return FileResponse(index_file)
    return HTMLResponse("<h1>Beacon Dashboard not found</h1>", status_code=404)


@app.get("/app.js")
def get_app_js() -> Any:
    """Serve the frontend JavaScript application script."""
    app_file = Path("web/app.js")
    if app_file.exists():
        return FileResponse(app_file, media_type="application/javascript")
    raise HTTPException(status_code=404, detail="app.js not found")


# Mount static web directory for assets
web_dir = Path("web")
if web_dir.is_dir():
    app.mount("/web", StaticFiles(directory="web"), name="web")

