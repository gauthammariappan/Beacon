"""Unit tests for Beacon v2.1 hardware telemetry recorder (tools/record.py)."""

import csv
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from tools.record import (
    HEADER,
    VALID_LABELS,
    get_output_filepath,
    initialize_csv,
    parse_serial_line,
    record_loop,
)


class DummySerial:
    """Mock serial port yielding specified lines."""

    def __init__(self, lines: list[bytes]):
        self.lines = list(lines)
        self.closed = False
        self.buffer_reset = False

    def readline(self) -> bytes:
        if self.lines:
            return self.lines.pop(0)
        # Raise KeyboardInterrupt when lines exhausted to simulate Ctrl+C
        raise KeyboardInterrupt

    def reset_input_buffer(self) -> None:
        self.buffer_reset = True

    def close(self) -> None:
        self.closed = True


class TestRecordTool(unittest.TestCase):
    def test_get_output_filepath(self):
        p1 = get_output_filepath(1)
        self.assertEqual(p1.name, "session1_train.csv")

        p2 = get_output_filepath(2)
        self.assertEqual(p2.name, "session2_test.csv")

        p3 = get_output_filepath(3)
        self.assertEqual(p3.name, "session3_test.csv")

    def test_parse_serial_line_valid(self):
        line = "E,1020,10.1,9.7,10.2,10.3,9.4,9.6,10.0,9.9,10.0"
        parsed = parse_serial_line(line)
        self.assertIsNotNone(parsed)
        self.assertEqual(len(parsed), 10)
        self.assertEqual(parsed[0], "1020")
        self.assertEqual(parsed[1], "10.1")
        self.assertEqual(parsed[-1], "10.0")

    def test_parse_serial_line_invalid_formats(self):
        # Incomplete line
        self.assertIsNone(parse_serial_line("E,1020,10.1,9.7"))
        # Missing E, prefix
        self.assertIsNone(parse_serial_line("DEBUG,booting"))
        # Non-numeric fields
        self.assertIsNone(parse_serial_line("E,1020,abc,9.7,10.2,10.3,9.4,9.6,10.0,9.9,10.0"))
        # Empty line
        self.assertIsNone(parse_serial_line(""))
        # Extra columns
        self.assertIsNone(parse_serial_line("E,1,2,3,4,5,6,7,8,9,10,11,12"))

    def test_initialize_csv_new_and_existing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test_session.csv"

            # 1. File does not exist: writes header
            initialize_csv(file_path)
            self.assertTrue(file_path.exists())

            with open(file_path, "r", encoding="utf-8") as f:
                reader = list(csv.reader(f))
                self.assertEqual(len(reader), 1)
                self.assertEqual(reader[0], HEADER)

            # 2. Append row to file
            with open(file_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["1", "A", "1000", "10", "10", "10", "5", "5", "5", "5", "5", "5"])

            # 3. Call initialize_csv again: does not duplicate header
            initialize_csv(file_path)
            with open(file_path, "r", encoding="utf-8") as f:
                reader = list(csv.reader(f))
                self.assertEqual(len(reader), 2)
                self.assertEqual(reader[0], HEADER)
                self.assertEqual(reader[1][1], "A")

    def test_record_loop_with_simulated_serial(self):
        raw_lines = [
            b"E,1000,10.0,20.0,30.0,5.0,5.0,5.0,5.0,5.0,5.0\n",
            b"GARBAGE_NOISE_LINE\n",  # Should be rejected
            b"E,1020,15.0,25.0,35.0,5.0,5.0,5.0,5.0,5.0,5.0\n",
        ]
        mock_ser = DummySerial(raw_lines)

        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "session1_train.csv"
            initialize_csv(out_file)

            # Simulate user inputs: "B" then "q"
            inputs = iter(["B", "q"])
            with patch("builtins.input", lambda _: next(inputs)):
                record_loop(ser=mock_ser, session=1, out_file=out_file)

            with open(out_file, "r", encoding="utf-8") as f:
                rows = list(csv.reader(f))

            # Header + 2 valid rows
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[0], HEADER)
            self.assertEqual(rows[1][0], "1")
            self.assertEqual(rows[1][1], "B")
            self.assertEqual(rows[1][2], "1000")
            self.assertEqual(rows[1][3], "10.0")

            self.assertEqual(rows[2][0], "1")
            self.assertEqual(rows[2][1], "B")
            self.assertEqual(rows[2][2], "1020")
            self.assertEqual(rows[2][3], "15.0")


if __name__ == "__main__":
    unittest.main()

