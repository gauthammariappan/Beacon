# The Pico streams one line per 16 ms frame while MIC is on:
#   E,<pico_ms>,L2500,M2500,R2500,L2000,M2000,R2000,L3000,M3000,R3000
# 2500 Hz is the beep. 2000 and 3000 Hz are the reference levels used for the purity check.
FIELDS = ["L2500", "M2500", "R2500", "L2000", "M2000", "R2000", "L3000", "M3000", "R3000"]


def parse_e_line(line):
    """Returns (pico_ms, [9 floats]) for an E line, or None for anything else."""
    parts = line.strip().split(",")
    if len(parts) != 11 or parts[0] != "E":
        return None
    try:
        return int(float(parts[1])), [float(v) for v in parts[2:]]
    except ValueError:
        return None
