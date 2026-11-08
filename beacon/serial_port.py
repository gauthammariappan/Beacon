# Talks to the Pico over its USB serial port (115200 baud, one command per line).
import errno
import fcntl
import glob
import os
import select
import subprocess
import termios
import time


def find_port():
    ports = sorted(glob.glob("/dev/cu.usbmodem*"))
    return ports[0] if ports else None


class PortBusy(SystemExit):
    """Another program already has the Pico open. Scripts just exit with the message."""


def _holders(port):
    """(pid, program name, full command) for every other process that has the port open."""
    try:
        pids = subprocess.run(["lsof", "-t", port], capture_output=True, text=True, timeout=10).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    for pid in pids:
        if pid == str(os.getpid()):
            continue
        comm = subprocess.run(["ps", "-o", "comm=", "-p", pid], capture_output=True, text=True).stdout.strip()
        cmd = subprocess.run(["ps", "-o", "command=", "-p", pid], capture_output=True, text=True).stdout.strip()
        if comm:
            found.append((pid, comm, cmd or comm))
    return found


def _free_from_arduino_monitor(port, holders):
    # The Arduino IDE's Serial Monitor keeps the port open. Only that helper is ever stopped.
    freed = False
    for pid, comm, _ in holders:
        if "serial-monitor" in comm:
            subprocess.run(["kill", pid])
            freed = True
    if freed:
        print("(Closed the Arduino Serial Monitor's connection so this script can use the Pico.)")
        time.sleep(0.5)
    return freed


def _busy_message(port, holders):
    if not holders:
        return (f"{port} is busy. Close anything else using the Pico (the Arduino Serial Monitor, "
                "another Beacon script) and try again.")
    who = "\n".join(f"    {cmd}   (pid {pid})" for pid, _, cmd in holders)
    which = "that" if len(holders) == 1 else "those"
    return (f"The Pico is already in use by:\n{who}\n"
            f"Stop {which} first (Ctrl+C in its Terminal window), then run this again.")


class PicoSerial:
    def __init__(self, port=None):
        self.port = port or find_port()
        if not self.port:
            raise SystemExit("Can't find the Pico. Is the USB cable plugged in all the way?")
        # Two scripts on one port each get half of the Pico's replies, which looks like random
        # glitches. So refuse to share: say who has it instead.
        others = _holders(self.port)
        if others and _free_from_arduino_monitor(self.port, others):
            others = _holders(self.port)
        if others:
            raise PortBusy(_busy_message(self.port, others))
        try:
            self.fd = self._open()
        except OSError as e:
            if e.errno == errno.EBUSY:
                raise PortBusy(_busy_message(self.port, _holders(self.port)))
            raise SystemExit(f"Can't open {self.port} ({e}).")
        self.buf = b""

    def _open(self):
        fd = os.open(self.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            fcntl.ioctl(fd, termios.TIOCEXCL)   # anyone else who tries to open it now gets "busy"
            a = termios.tcgetattr(fd)
            a[0] = 0
            a[1] = 0
            a[3] = 0
            a[2] |= termios.CREAD | termios.CLOCAL
            a[4] = a[5] = termios.B115200
            termios.tcsetattr(fd, termios.TCSANOW, a)
        except BaseException:
            os.close(fd)
            raise
        return fd

    def write(self, cmd):
        try:
            os.write(self.fd, (cmd.strip() + "\n").encode())
        except OSError:
            raise ConnectionError("lost the connection to the Pico")

    def lines(self, timeout=0.1):
        """Whatever complete lines arrive within `timeout` seconds."""
        try:
            r, _, _ = select.select([self.fd], [], [], timeout)
            if r:
                data = os.read(self.fd, 8192)
                if not data:   # "ready" with nothing to read means the device went away
                    raise ConnectionError("lost the connection to the Pico")
                self.buf += data
        except BlockingIOError:
            pass
        except OSError:
            raise ConnectionError("lost the connection to the Pico")
        *done, self.buf = self.buf.split(b"\n")
        return [d.decode(errors="replace").strip() for d in done if d.strip()]

    def close(self):
        time.sleep(0.05)   # let the last command (usually LASER,0) leave before the port closes
        os.close(self.fd)
