# Talks to the Pico over its USB serial port (115200 baud, one command per line).
import errno
import glob
import os
import select
import subprocess
import termios
import time


def find_port():
    ports = sorted(glob.glob("/dev/cu.usbmodem*"))
    return ports[0] if ports else None


def _free_from_arduino_monitor(port):
    # The Arduino IDE's Serial Monitor keeps the port open. Only that helper is ever stopped.
    pids = subprocess.run(["lsof", "-t", port], capture_output=True, text=True).stdout.split()
    freed = False
    for pid in pids:
        name = subprocess.run(["ps", "-o", "comm=", "-p", pid], capture_output=True, text=True).stdout
        if "serial-monitor" in name:
            subprocess.run(["kill", pid])
            freed = True
    if freed:
        print("(Closed the Arduino Serial Monitor's connection so this script can use the Pico.)")
        time.sleep(0.5)
    return freed


class PicoSerial:
    def __init__(self, port=None):
        self.port = port or find_port()
        if not self.port:
            raise SystemExit("Can't find the Pico. Is the USB cable plugged in all the way?")
        try:
            self.fd = self._open()
        except OSError as e:
            if e.errno == errno.EBUSY and _free_from_arduino_monitor(self.port):
                self.fd = self._open()
            else:
                raise SystemExit(f"Can't open {self.port} ({e}). Close the Arduino Serial Monitor and try again.")
        self.buf = b""

    def _open(self):
        fd = os.open(self.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        a = termios.tcgetattr(fd)
        a[0] = 0
        a[1] = 0
        a[3] = 0
        a[2] |= termios.CREAD | termios.CLOCAL
        a[4] = a[5] = termios.B115200
        termios.tcsetattr(fd, termios.TCSANOW, a)
        return fd

    def write(self, cmd):
        os.write(self.fd, (cmd.strip() + "\n").encode())

    def lines(self, timeout=0.1):
        """Whatever complete lines arrive within `timeout` seconds."""
        try:
            r, _, _ = select.select([self.fd], [], [], timeout)
            if r:
                self.buf += os.read(self.fd, 8192)
        except BlockingIOError:
            pass
        except OSError:
            raise ConnectionError("lost the connection to the Pico")
        *done, self.buf = self.buf.split(b"\n")
        return [d.decode(errors="replace").strip() for d in done if d.strip()]

    def close(self):
        os.close(self.fd)
