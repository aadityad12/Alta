# /// script
# requires-python = ">=3.11"
# dependencies = ["pyserial", "pyyaml"]
# ///
"""Measure a lab's nets with the real pod, correct circuit + every fault (#4 verify step). ~10 min a lab.

    uv run labs/measure.py lab1-led          # or lab2-light; --port /dev/cu.usbmodemXXXX
    uv run labs/measure.py lab1-led --only led_reversed   # redo just one state

Flash the real firmware first (cd firmware && make flash) and close the server / any serial
monitor. You place one probe per net once, then stage each state when asked. Results go to
labs/<lab>/measured.yaml (Engineer A copies them into lab.yaml and sets verified: true),
and a summary is printed to paste into #4.
"""

import argparse
import glob
import json
import statistics as st
import sys
import time
from pathlib import Path

import serial
import yaml

LABS = Path(__file__).resolve().parent
PORT_GLOBS = ("/dev/cu.usbmodem*", "/dev/cu.usbserial*", "/dev/cu.wchusbserial*", "/dev/ttyACM*", "/dev/ttyUSB*")
PROBES = ("Y", "B", "G", "W")
COLOR = {"Y": "yellow", "B": "blue", "G": "green", "W": "white"}
LIGHT = {"room": "normal room light", "covered": "the sensor covered with a finger", "bright": "a phone flashlight right on the sensor"}


def probe_point(net: dict) -> str:
    """Where to put a probe for this net: its first row strip, else its rail."""
    for h in net["holes"]:
        if not h.startswith("rail:"):
            return f"row {h.split(':')[0]}" if ":" in h else f"hole {h}"
    rail = net["holes"][0]
    return f"the {'+' if rail.endswith('+') else '−'} rail (next to column {rail[5]})"


class Pod:
    def __init__(self, port: str):
        self.ser = serial.Serial(port, 115200, timeout=0.1)
        time.sleep(2.0)  # the Uno resets when the port opens
        self.ser.reset_input_buffer()

    def samples(self, secs: float) -> list[dict]:
        # Drop what queued up while we waited at a prompt (the Uno's USB chip holds old lines
        # that reset_input_buffer can't reach), so every reading is from after Enter.
        self.ser.reset_input_buffer()
        end = time.monotonic() + 0.6
        while time.monotonic() < end:
            self.ser.read(self.ser.in_waiting or 1)
        out, end = [], time.monotonic() + secs
        while time.monotonic() < end:
            line = self.ser.readline().decode(errors="replace").strip()
            try:
                m = json.loads(line)
            except ValueError:
                continue
            if "seq" in m:
                out.append(m)
        return out


def ask(prompt: str) -> str:
    return input(f"\n→ {prompt} ").strip().lower()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lab", help="lab id, e.g. lab1-led")
    ap.add_argument("--port")
    ap.add_argument("--secs", type=float, default=2.0, help="seconds to average per state")
    ap.add_argument("--only", help="measure just this state (normal, normal:covered, or a fault id)")
    args = ap.parse_args()

    lab = yaml.safe_load((LABS / args.lab / "lab.yaml").read_text())
    nets = lab["nets"]
    if len(nets) > len(PROBES):
        sys.exit(f"{len(nets)} nets but only 4 probes; split the run")
    port = args.port or next(iter(sorted(p for g in PORT_GLOBS for p in glob.glob(g))), None)
    if not port:
        sys.exit("No Uno found. Plug it in or pass --port.")

    has_light = args.lab.startswith("lab2")
    states = [("normal:" + k, f"the correct circuit, with {v}") for k, v in LIGHT.items()] if has_light else [("normal", "the correct circuit")]
    states += [(f["id"], f["how_to_stage"]) for f in lab["faults"]]
    if args.only:
        states = [s for s in states if s[0] == args.only]
        if not states:
            sys.exit(f"no state {args.only!r}")

    print(f"{lab['title']} · port {port}")
    pod = Pod(port)
    if not pod.samples(1.0):
        sys.exit("No sample lines. Is the real firmware flashed (make flash)? Is the server/monitor closed?")

    print("\nBuild the correct circuit (labs/README.md placement), then plug in the probes:")
    for p, n in zip(PROBES, nets):
        print(f"   {COLOR[p]:>6} probe ({p}) → {probe_point(n)}   [{n['label']}]")
    ask("Probes in? Press Enter.")

    out_path = LABS / args.lab / "measured.yaml"
    result = yaml.safe_load(out_path.read_text()) if out_path.exists() and args.only else {}
    result.update({"lab": args.lab, "port": port, "measured_at": time.strftime("%Y-%m-%d %H:%M"),
                   "probes": {p: n["id"] for p, n in zip(PROBES, nets)}})
    result.setdefault("states", {})
    readings = {f["id"]: f.get("readings", {}) for f in lab["faults"]}

    for i, (sid, how) in enumerate(states):
        prev_fault = i > 0 and not states[i - 1][0].startswith("normal")
        back = "Undo the last fault so the circuit is correct again. Then: " if prev_fault else ""
        ask(f"[{i + 1}/{len(states)}] {sid}: {back}{how.rstrip('.')}. Press Enter when it's set (hands off the board).")
        ss = pod.samples(args.secs)
        vcc = round(st.mean(s["vcc"] for s in ss))
        row = {}
        print(f"   {'net':<14} {'mean':>6} {'lo':>6} {'hi':>6}   draft")
        for k, n in enumerate(nets):
            mean = round(st.mean(s["mv"][k] for s in ss))
            lo = min(s["lo"][k] for s in ss)
            hi = max(s["hi"][k] for s in ss)
            draft = readings.get(sid, {}).get(n["id"], n.get("expected_mv")) if not sid.startswith("normal") else n.get("expected_mv")
            flag = "" if draft is None or abs(mean - draft) <= max(n.get("tol_mv", 100), 150) else "  ← differs from draft"
            print(f"   {n['id']:<14} {mean:>6} {lo:>6} {hi:>6}   {draft}{flag}")
            row[n["id"]] = {"mv": mean, "lo": lo, "hi": hi}
        result["states"][sid] = {"vcc": vcc, "nets": row}
        out_path.write_text(yaml.safe_dump(result, sort_keys=False))  # save as we go

    print("\n" + "─" * 60 + f"\nSaved {out_path.relative_to(LABS.parent)}. Paste into #4:\n")
    print(f"Measured {args.lab} with the real pod ({result['measured_at']}), mV:\n")
    ids = [n["id"] for n in nets]
    print("| state | " + " | ".join(ids) + " | vcc |\n|---|" + "---|" * (len(ids) + 1))
    for sid, s in result["states"].items():
        print(f"| {sid} | " + " | ".join(f"{s['nets'][n]['mv']} ({s['nets'][n]['lo']}–{s['nets'][n]['hi']})" for n in ids) + f" | {s['vcc']} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
