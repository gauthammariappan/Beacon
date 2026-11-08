"""FastAPI backend server for Beacon v2.1 acoustic localization."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import csv
import glob
import json
import os
from pathlib import Path
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from beacon.features import extract_spatial_features
from beacon.incidents import Incident, IncidentManager, IncidentState
from beacon.location_model import LocationClassifier
from beacon.signal import SignalProcessor

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


async def run_serial_reader() -> None:
    """Layer 2 ingest loop: reads from hardware serial port, or replays recorded CSV."""
    serial_port = os.getenv("SERIAL_PORT")
    if not serial_port:
        matches = glob.glob("/dev/tty.usbmodem*") + glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")
        if matches:
            serial_port = matches[0]

    ser = None
    if serial_port:
        try:
            import serial
            ser = serial.Serial(serial_port, baudrate=115200, timeout=0.1)
            print(f"[Serial] Connected to hardware Pico on {serial_port}")
        except Exception as e:
            print(f"[Serial] Could not open {serial_port} ({e}). Falling back to simulation/replay.")
            ser = None

    if ser is not None:
        # Hardware serial loop
        loop = asyncio.get_running_loop()
        while True:
            try:
                raw_line = await loop.run_in_executor(None, ser.readline)
                if not raw_line:
                    await asyncio.sleep(0.005)
                    continue
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("E,"):
                    continue

                await handle_serial_line(line)
            except asyncio.CancelledError:
                ser.close()
                break
            except Exception:
                await asyncio.sleep(0.01)
    else:
        # Replay simulator loop (Layer 2 replay mode)
        test_csv_path = Path("recordings/session2_test.csv")
        while True:
            try:
                if test_csv_path.exists():
                    with open(test_csv_path, mode="r", encoding="utf-8") as f:
                        reader = csv.reader(f)
                        for row in reader:
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
                    # Synthetic baseline frames if CSV missing
                    now_ms = int(time.time() * 1000)
                    line = f"E,{now_ms},10.0,10.0,10.0,10.0,10.0,10.0,10.0,10.0,10.0"
                    await handle_serial_line(line)
                    await asyncio.sleep(0.02)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(0.05)


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
        # Brain 1: Spatial Location Classifier (Layer 4)
        loc_res = location_classifier.predict(event.features, update_vote=True)

        # Brain 2: Cadence Tracker (Layer 4)
        alarm_res = incident_manager.cadence_tracker.feed_beep(event)

        # Action: Incident Manager State Machine (Layer 5)
        incident = incident_manager.feed_beep(
            location_result=loc_res,
            alarm_result=alarm_res,
            event=event,
        )

        if incident is not None:
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


@app.get("/layout")
def get_layout() -> dict[str, Any]:
    """Return physical rack and microphone positions."""
    layout_path = Path("rack_layout.json")
    if layout_path.exists():
        try:
            with open(layout_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_LAYOUT


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


@app.get("/model/metrics")
def get_model_metrics() -> dict[str, Any]:
    """Serve location model evaluation metrics and confusion matrices."""
    metrics_path = Path("artifacts/location_metrics.json")
    if not metrics_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Model metrics not found. Run tools/train_location.py first.",
        )
    with open(metrics_path, "r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/incidents")
def get_incidents() -> dict[str, Any]:
    """Return current active incident and historical incidents."""
    active = incident_manager.get_active_incident()
    return {
        "active": active.to_dict() if active is not None else None,
        "history": incident_manager.get_history(),
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

