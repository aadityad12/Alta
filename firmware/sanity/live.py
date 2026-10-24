# /// script
# requires-python = ">=3.11"
# dependencies = ["pyserial"]
# ///
"""Live view of the pod while you poke at the wiring (needs sanity.ino on the Uno).

    uv run firmware/sanity/live.py            # Ctrl+C to stop

Every ~1.5 s it says what each probe is touching (GND, 5 V, floating or a
voltage) and whether the talk button is pressed.
"""

import glob
import sys
import time

import serial

PROBES = ("Y", "B", "G", "W")


def parse(line: str) -> dict | None:
    out = {}
    for tok in line.split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[k] = int(v) if v.isdigit() else v
    return out if all(p in out for p in PROBES) and "btn" in out else None


def describe(vals: list[int]) -> str:
    lo, hi = min(vals), max(vals)
    if hi - lo > 80:
        return "floating  "  # touching nothing powered: noise swings it around
    v = sum(vals) / len(vals)
    if v < 20:
        return "GND       "
    if v > 1000:
        return "5 V       "
    return f"{v * 5 / 1023:4.2f} V    "


def main() -> int:
    ports = sorted(glob.glob("/dev/cu.usbmodem*") + glob.glob("/dev/cu.usbserial*") + glob.glob("/dev/ttyACM*"))
    if not ports:
        sys.exit("No Uno found. Plug it in.")
    ser = serial.Serial(sys.argv[1] if len(sys.argv) > 1 else ports[0], 115200, timeout=1)
    time.sleep(2)  # the Uno resets when the port opens
    ser.reset_input_buffer()
    print("Watching the pod. Ctrl+C to stop.\n")
    window: list[dict] = []
    try:
        while True:
            s = parse(ser.readline().decode(errors="replace"))
            if not s:
                continue
            window.append(s)
            if len(window) >= 8:  # ~1.6 s: long enough to catch a floating probe swinging
                cells = "  ".join(f"{p}: {describe([w[p] for w in window])}" for p in PROBES)
                btn = "PRESSED " if any(w["btn"] == 0 for w in window) else "released"
                print(f"\r{cells}  button: {btn}", end="", flush=True)
                window = []
    except KeyboardInterrupt:
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
