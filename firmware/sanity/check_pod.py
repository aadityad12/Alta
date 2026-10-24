# /// script
# requires-python = ">=3.11"
# dependencies = ["pyserial"]
# ///
"""Guided wiring check for the probe pod (#5). Pairs with sanity.ino.

    uv run firmware/sanity/check_pod.py --upload     # flash sanity.ino, then test
    uv run firmware/sanity/check_pod.py              # sketch already on the Uno
    uv run firmware/sanity/check_pod.py --port /dev/cu.usbserial-110

It walks you through: all probes on the − rail, all on the + rail, the talk
button, and the status LED colors. Then it prints PASS/FAIL per check plus a
summary to paste into issue #5. Exits 1 if anything failed.
"""

import argparse
import glob
import subprocess
import sys
import time
from pathlib import Path

import serial

SKETCH = Path(__file__).resolve().parent
PROBES = ("Y", "B", "G", "W")
GND_MAX = 10      # ≤ ~50 mV counts as ground
VCC_MIN = 1013    # ≥ ~4.95 V (relative to the Uno's own 5 V) counts as 5 V
PORT_GLOBS = ("/dev/cu.usbmodem*", "/dev/cu.usbserial*", "/dev/cu.wchusbserial*", "/dev/ttyACM*", "/dev/ttyUSB*")


def find_port() -> str:
    ports = sorted(p for g in PORT_GLOBS for p in glob.glob(g))
    if not ports:
        sys.exit("No Uno found. Plug in the USB cable (clones show up as /dev/cu.usbserial-* or wchusbserial*).")
    if len(ports) > 1:
        print(f"Several ports found, using {ports[0]} (others: {ports[1:]}). Pass --port to choose.")
    return ports[0]


def parse(line: str) -> dict | None:
    """'Y=0 B=1023 G=511 W=3 btn=1 led=R [inv]' -> dict, or None for other lines."""
    out = {}
    for tok in line.split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[k] = int(v) if v.lstrip("-").isdigit() else v
    return out if all(p in out for p in PROBES) and "btn" in out else None


def samples(ser: serial.Serial, n: int = 10) -> list[dict]:
    ser.reset_input_buffer()
    got: list[dict] = []
    deadline = time.monotonic() + n * 0.2 + 3
    while len(got) < n and time.monotonic() < deadline:
        s = parse(ser.readline().decode(errors="replace"))
        if s:
            got.append(s)
    if not got:
        sys.exit("No readings from the pod. Is sanity.ino uploaded? Try --upload.")
    return got


def ask(prompt: str) -> str:
    return input(f"\n→ {prompt} ").strip().lower()


def explain_rail(name: str, vals: list[int], want_gnd: bool) -> str:
    lo, hi = min(vals), max(vals)
    if hi - lo > 60:
        return f"jumps {lo}–{hi}: floating. Check Uno A-pin → row a, the 10 kΩ across the gap, and that the probe wire is in the right row."
    if want_gnd and lo > 1000:
        return f"reads {lo} (5 V): the probe is on the + rail, or the rails are swapped."
    if not want_gnd and hi < 20:
        return f"reads {hi} (0 V): the probe is on the − rail, or the rails are swapped."
    return f"reads {lo}–{hi}."


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port")
    ap.add_argument("--upload", action="store_true", help="compile + upload sanity.ino with arduino-cli first")
    args = ap.parse_args()
    port = args.port or find_port()

    if args.upload:
        print(f"Uploading sanity.ino to {port} …")
        subprocess.run(["arduino-cli", "compile", "--fqbn", "arduino:avr:uno", "--upload", "-p", port, str(SKETCH)], check=True)

    ser = serial.Serial(port, 115200, timeout=1)
    time.sleep(2)  # the Uno resets when the port opens
    results: list[tuple[str, bool, str]] = []

    for want_gnd, rail, label in ((True, "− (GND)", "≈0"), (False, "+ (5 V)", "≈1023")):
        ask(f"Plug ALL FOUR probe wires into the {rail} rail of the lab board, then press Enter.")
        got = samples(ser)
        for p in PROBES:
            vals = [s[p] for s in got]
            ok = max(vals) <= GND_MAX if want_gnd else min(vals) >= VCC_MIN
            results.append((f"{p} probe on {rail} reads {label}", ok, explain_rail(p, vals, want_gnd)))

    ask("Unplug the probes. HOLD the talk button down, then press Enter (keep holding).")
    held = [s["btn"] for s in samples(ser)]
    ask("Release the button, then press Enter.")
    free = [s["btn"] for s in samples(ser)]
    results.append(("button reads 0 while held", held.count(0) >= len(held) * 0.8,
                    f"held: {held}" + ("  (never 0: D2 → button → GND wiring, or same-side legs)" if 0 not in held else "")))
    results.append(("button reads 1 when released", all(b == 1 for b in free),
                    f"released: {free}" + ("  (stuck at 0: the legs you used are always connected; use diagonal legs)" if 0 in free else "")))

    led_type = "unknown"
    print("\nWatch the status LED for a few seconds. It should step red → green → blue → off, once a second.")
    a = ask("Did it? [y = yes / n = no or wrong colors / x = it's mostly ON and goes dark one color at a time]")
    if a == "x":
        ser.write(b"i")
        a = ask("Inverted the outputs for a common-anode LED. Does it go red → green → blue → off now? [y/n]")
        led_type = "common-anode" if a == "y" else "unknown"
    elif a == "y":
        led_type = "common-cathode"
    ok = a == "y"
    detail = f"type: {led_type}"
    if not ok:
        seen = ask("What order did you see? (e.g. 'r b g', or 'none')")
        if seen in ("", "none", "nothing"):
            detail += "; never lit. Probably common-anode with its long leg on GND: move the 27a jumper to the + rail and rerun"
        else:
            detail += f"; saw: {seen} (wrong order is fine: tell Engineer A and we remap D9–D11 in firmware)"
    results.append(("status LED shows red, green, blue", ok, detail))
    ser.close()

    print("\n" + "─" * 60)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}   {detail}")
    failed = [r for r in results if not r[1]]
    print("─" * 60)
    print("\nPaste into #5:\n")
    print(f"Sanity test (`check_pod.py`, port `{port}`): **{len(results) - len(failed)}/{len(results)} pass**, LED is **{led_type}**")
    for name, ok, detail in results:
        print(f"- {'✅' if ok else '❌'} {name}: {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
