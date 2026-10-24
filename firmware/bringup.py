# /// script
# requires-python = ">=3.11"
# dependencies = ["pyserial"]
# ///
"""Guided bring-up of the real pod with the real firmware (#6, #7, #8). ~10 minutes.

    cd firmware && make flash            # LED=ca make flash for a common-anode LED
    uv run bringup.py                    # or: uv run bringup.py --port /dev/cu.usbmodemXXXX

Close the server and any serial monitor first (the port can only be open once).
Walks you through #7's test matrix (GND, 5 V, 3.3 V, divider), the LED colors, PING,
the talk button and a 60 s parse soak, then prints a summary to paste into the issues.
"""

import argparse
import glob
import json
import statistics as st
import sys
import time

import serial

PORT_GLOBS = ("/dev/cu.usbmodem*", "/dev/cu.usbserial*", "/dev/cu.wchusbserial*", "/dev/ttyACM*", "/dev/ttyUSB*")
NAMES = ("Y", "B", "G", "W")
results: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> bool:
    results.append((ok, name, detail))
    print(f"   {'PASS' if ok else 'FAIL'}  {name}   {detail}")
    return ok


def ask(prompt: str) -> str:
    return input(f"\n→ {prompt} ").strip().lower()


class Pod:
    def __init__(self, port: str) -> None:
        self.ser = serial.Serial(port, 115200, timeout=0.1)   # opening resets the Uno
        self.buf = b""
        self.bad = 0
        self.hello = None
        self.skip_partial = True   # we join mid-line: drop everything up to the first \n

    def lines(self, seconds: float) -> list[dict]:
        out, end = [], time.monotonic() + seconds
        while time.monotonic() < end:
            self.buf += self.ser.read(self.ser.in_waiting or 1)
            if self.skip_partial:   # drop the first fragment only if it's a cut-off line
                if b"\n" not in self.buf:
                    continue
                head, rest = self.buf.split(b"\n", 1)
                if not head.lstrip().startswith(b"{"):
                    self.buf = rest
                self.skip_partial = False
            *raw, self.buf = self.buf.split(b"\n")
            for r in raw:
                r = r.strip()
                if not r:
                    continue
                try:
                    msg = json.loads(r)
                except ValueError:
                    self.bad += 1
                    continue
                if "hello" in msg:
                    self.hello = msg
                out.append(msg)
        return out

    def flush(self) -> None:
        self.ser.reset_input_buffer()
        self.buf = b""
        self.skip_partial = True

    def samples(self, seconds: float) -> list[dict]:
        self.flush()
        return [m for m in self.lines(seconds) if "seq" in m]

    def send(self, cmd: str) -> None:
        self.ser.write(f"{cmd}\n".encode())


def avg(ss: list[dict], i: int, key: str = "mv") -> float:
    return st.mean(s[key][i] for s in ss) if ss else float("nan")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port")
    ap.add_argument("--soak", type=float, default=60)
    args = ap.parse_args()
    port = args.port or next(iter(sorted(p for g in PORT_GLOBS for p in glob.glob(g))), None)
    if not port:
        sys.exit("No Uno found. Plug it in or pass --port.")

    print(f"Opening {port} (the Uno resets; watch the status LED: red → green → blue → off)")
    pod = Pod(port)
    first = pod.lines(3.0)
    check(pod.hello is not None and pod.hello.get("fw") == "0.1.0", "#6 hello line after reset", str(pod.hello))
    ss = [m for m in first if "seq" in m]
    if not ss:
        print("No sample lines. Is the firmware flashed (make flash)? Is the server/monitor closed?")
        return 1
    a = ask("Did the status LED flash red → green → blue at boot? [y/n]")
    check(a == "y", "#8 boot self-test colors")

    # ---- #7 rate + format ----
    ss = pod.samples(3.0)
    seq_ok = all(b["seq"] == a["seq"] + 1 for a, b in zip(ss, ss[1:]))
    keys_ok = all(set(s) == {"seq", "t", "mv", "lo", "hi", "vcc", "btn"} for s in ss)
    steps = sorted({b["t"] - a["t"] for a, b in zip(ss, ss[1:])})
    # 20 Hz by the pod's own clock (t steps of exactly 50 ms, no gaps in seq); wall rate as a floor.
    check(steps == [50] and seq_ok and keys_ok and len(ss) / 3 >= 18, "#7 20 Hz, §2 keys, seq contiguous",
          f"t steps {steps} ms, {len(ss) / 3:.1f} lines/s")
    vcc = st.mean(s["vcc"] for s in ss)
    print(f"   vcc = {vcc:.0f} mV (if a multimeter is around, compare it with the Uno's 5V pin)")

    # ---- #7 test matrix ----
    steps = [
        ("all FOUR probes on the lab board's − (GND) rail", lambda m, v: m < 20, "< 20 mV"),
        ("all FOUR probes on the lab board's + (5 V) rail", lambda m, v: abs(m - v) <= 30, "= vcc ± 30 mV"),
        ("all FOUR probes on the Uno's 3.3V pin", lambda m, v: abs(m - 3300) <= 100, "≈ 3300 mV"),
    ]
    for where, ok, want in steps:
        ask(f"Put {where}, then press Enter.")
        ss = pod.samples(1.5)
        v = st.mean(s["vcc"] for s in ss)
        for i, n in enumerate(NAMES):
            m = avg(ss, i)
            spread = avg(ss, i, "hi") - avg(ss, i, "lo")
            check(ok(m, v), f"#7 {n} on {where.split(' on ')[-1]} {want}", f"{m:.0f} mV (lo–hi {spread:.0f}, vcc {v:.0f})")
    a = ask("Optional: build a 10k/10k divider (5 V → 10k → row → 10k → GND), put Y in the middle row, Enter. (s = skip)")
    if a != "s":
        ss = pod.samples(1.5)
        m, v = avg(ss, 0), st.mean(s["vcc"] for s in ss)
        check(abs(m - v / 2) <= 50, "#7 Y on a 10k/10k divider ≈ vcc/2", f"{m:.0f} mV vs {v / 2:.0f}")

    # ---- #8 LED + commands ----
    for cmd, color in (("LED LISTEN", "green"), ("LED THINK", "blue"), ("LED SPEAK", "white"),
                       ("LED ERROR", "red"), ("LED IDLE", "off")):
        pod.send(cmd)
        a = ask(f"Sent '{cmd}'. Is the status LED {color.upper()}? [y/n]")
        check(a == "y", f"#8 {cmd} → {color}")
    pod.flush()
    pod.send("PING")
    pong = [m for m in pod.lines(0.5) if "pong" in m]
    check(bool(pong) and pong[0].get("fw") == "0.1.0", "#8 PING → pong", str(pong[:1]))
    pod.send("HELLO?")
    err = [m for m in pod.lines(0.5) if "err" in m]
    check(err == [{"err": "unknown_cmd"}], "#8 unknown command → err", str(err[:1]))

    # ---- #8 button ----
    ask("Press Enter, then press and hold the talk button for about a second, then release it.")
    pod.flush()
    msgs = pod.lines(5.0)
    evts = [m for m in msgs if m.get("evt") == "btn"]
    held = [m["btn"] for m in msgs if "seq" in m]
    check([e["down"] for e in evts][:2] == [1, 0], "#8 button → evt down:1 then down:0", str(evts[:4]))
    check(held.count(1) >= 5, "#8 samples carry btn:1 while held", f"{held.count(1)} samples")
    if len(evts) > 2:
        print("   (more than one press/release seen: bounce, or you pressed twice)")

    # ---- #7 soak ----
    print(f"\nSoak: parsing every line for {args.soak:.0f} s, hands off…")
    pod.bad = 0
    ss = pod.samples(args.soak)
    check(pod.bad == 0 and 19 <= len(ss) / args.soak <= 21, f"#7 {args.soak:.0f} s soak: every line parses",
          f"{len(ss)} samples = {len(ss) / args.soak:.2f} Hz, {pod.bad} bad lines")

    failed = [r for r in results if not r[0]]
    print("\n" + "─" * 60 + f"\nPaste into #6/#7/#8:\n\nBring-up on the real pod (`bringup.py`, {port}): "
          f"**{len(results) - len(failed)}/{len(results)} pass**, vcc ≈ {vcc:.0f} mV")
    for ok, name, detail in results:
        print(f"- {'✅' if ok else '❌'} {name}: {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
