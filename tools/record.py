"""Beacon v2.1 · Hardware Acoustic Telemetry Recorder (Layer 2 CLI).

Records real 50 Hz acoustic telemetry from Raspberry Pi Pico 2W over USB CDC
serial, labels frames with ground-truth rack positions (A, B, C, D, E, NONE),
and appends them to structured CSV datasets for training and testing.
"""

from __future__ import annotations

import argparse
import csv
import glob
import os
from pathlib import Path
import sys
from typing import Any, Optional

try:
    import serial
except ImportError:
    serial = None

HEADER = [
    "session",
    "label",
    "t_ms",
    "L25",
    "M25",
    "R25",
    "L20",
    "M20",
    "R20",
    "L30",
    "M30",
    "R30",
]

VALID_LABELS = {"A", "B", "C", "D", "E", "NONE"}


def find_serial_port() -> Optional[str]:
    """Auto-detect Raspberry Pi Pico USB CDC serial port."""
    env_port = os.getenv("SERIAL_PORT")
    if env_port:
        return env_port

    patterns = [
        "/dev/cu.usbmodem*",
        "/dev/tty.usbmodem*",
        "/dev/ttyACM*",
        "/dev/ttyUSB*",
    ]
    for pattern in patterns:
        matches = glob.glob(pattern)
        if matches:
            return matches[0]

    try:
        from serial.tools import list_ports

        for p in list_ports.comports():
            desc = (p.description or "").lower()
            dev = (p.device or "").lower()
            if "pico" in desc or "raspberry" in desc or "usbmodem" in dev:
                return p.device
    except Exception:
        pass

    return None


def get_output_filepath(session: int, base_dir: Path | str = "recordings") -> Path:
    """Return output CSV filepath based on session number."""
    base = Path(base_dir)
    filename = f"session{session}_train.csv" if session == 1 else f"session{session}_test.csv"
    return base / filename


def initialize_csv(file_path: Path) -> None:
    """Create CSV file with header row if it does not exist or is empty."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    if not file_path.exists() or file_path.stat().st_size == 0:
        with open(file_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(HEADER)


def parse_serial_line(line: str) -> Optional[list[str]]:
    """Validate and parse 50 Hz serial telemetry line.

    Expected format: E,<ms>,L25,M25,R25,L20,M20,R20,L30,M30,R30
    Returns 10-element list of strings [t_ms, L25, ..., R30] or None if invalid.
    """
    raw = line.strip()
    if not raw.startswith("E,"):
        return None

    parts = [t.strip() for t in raw.split(",")]
    if len(parts) != 11 or parts[0] != "E":
        return None

    # Verify all 10 telemetry fields are valid numeric representations
    try:
        for val in parts[1:]:
            float(val)
    except (ValueError, TypeError):
        return None

    return parts[1:]


def record_loop(ser: Any, session: int, out_file: Path) -> None:
    """Interactive loop to record labeled serial frames per rack position."""
    f_out = open(out_file, mode="a", newline="", encoding="utf-8")
    writer = csv.writer(f_out)

    try:
        while True:
            try:
                raw_input = input("Enter rack label to record (A, B, C, D, E, NONE) or 'q' to quit: ")
            except (KeyboardInterrupt, EOFError):
                print("\nExiting recorder.")
                break

            choice = raw_input.strip()
            if choice.lower() in ("q", "quit", "exit"):
                print("Exiting recorder.")
                break

            label = choice.upper()
            if label not in VALID_LABELS:
                print(f"Invalid label '{choice}'. Please enter one of: A, B, C, D, E, NONE (or 'q' to quit).")
                continue

            print(f"Recording for rack {label}... Press Ctrl+C to stop recording this rack.")

            # Clear serial buffer before starting rack recording
            if hasattr(ser, "reset_input_buffer"):
                ser.reset_input_buffer()

            recorded_count = 0
            try:
                while True:
                    raw_bytes = ser.readline()
                    if not raw_bytes:
                        continue

                    decoded = raw_bytes.decode("utf-8", errors="replace").strip()
                    parsed = parse_serial_line(decoded)
                    if parsed is None:
                        continue

                    row = [session, label] + parsed
                    writer.writerow(row)
                    recorded_count += 1

                    if recorded_count % 10 == 0:
                        f_out.flush()
                        print(f"  [{label}] Recorded {recorded_count} frames...", end="\r")

            except KeyboardInterrupt:
                f_out.flush()
                print(f"\nStopped recording for rack {label}. Saved {recorded_count} frames to {out_file.name}.")

    finally:
        f_out.flush()
        f_out.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Beacon v2.1 Live Hardware Telemetry Recorder")
    parser.add_argument("--session", type=int, default=1, help="Session number (default: 1)")
    parser.add_argument("--port", type=str, default=None, help="Serial port (default: auto-detect)")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate (default: 115200)")
    args = parser.parse_args()

    port = args.port or find_serial_port()
    if not port:
        print("Error: No Raspberry Pi Pico serial port detected. Please specify --port <device>.")
        sys.exit(1)

    if serial is None:
        print("Error: 'pyserial' is not installed. Please run: pip install pyserial")
        sys.exit(1)

    out_file = get_output_filepath(args.session)
    initialize_csv(out_file)

    try:
        ser = serial.Serial(port, baudrate=args.baud, timeout=0.1)
    except Exception as e:
        print(f"Error opening serial port {port}: {e}")
        sys.exit(1)

    print(f"Connected to Pico on {port} @ {args.baud} baud.")
    print(f"Saving session {args.session} to {out_file}")

    try:
        record_loop(ser=ser, session=args.session, out_file=out_file)
    finally:
        ser.close()
        print("Serial port closed.")


if __name__ == "__main__":
    main()
