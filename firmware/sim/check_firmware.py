"""The real pod firmware (bench.elf in simavr) talking to the server's real serial bridge.

    cd firmware && make check            (LED=ca make check for the common-anode build)

Covers #6 (hello), #7 (20 Hz samples in the exact §2 format + the voltage test matrix) and
#8 (button events, LED commands, PING/err), plus a reset and 60 s of zero-error parsing.
Run from server/ (make check does that) so `bench` imports. Exits 1 on any failure.
"""

import asyncio
import logging
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, os.getcwd())
from bench import bus as ev  # noqa: E402
from bench.bus import EventBus  # noqa: E402
from bench.pod import PodBridge  # noqa: E402

ELF, SIM = sys.argv[1], sys.argv[2]
COMMON_ANODE = "-a" in sys.argv[3:]
LINK = f"/tmp/bench-pod-fwcheck-{os.getpid()}"
SAMPLE_KEYS = {"seq", "t", "mv", "lo", "hi", "vcc", "btn"}
LONG = os.environ.get("LONG", "60")   # seconds for the parse-everything soak test

results: list[bool] = []


def check(ok: bool, name: str, detail: str = "") -> bool:
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"   {detail}" if detail else ""), flush=True)
    return ok


class Sim:
    def __init__(self) -> None:
        args = [SIM, ELF, "-l", LINK] + (["-a"] if COMMON_ANODE else [])
        self.p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, bufsize=1)
        self.out: list[tuple[float, str]] = []
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        for line in self.p.stdout:
            self.out.append((time.monotonic(), line.rstrip()))

    def cmd(self, text: str) -> None:
        self.p.stdin.write(text + "\n")
        self.p.stdin.flush()

    def leds(self, since: float = 0) -> list[tuple[int, str]]:
        """(sim ms, color) for every LED change the harness saw."""
        got = []
        for t, line in self.out:
            m = re.match(r"\[\s*(\d+) ms\] LED (\w+)", line)
            if m and t >= since:
                got.append((int(m[1]), m[2]))
        return got

    def stop(self) -> None:
        self.p.terminate()
        self.p.wait(timeout=5)


class BadLines(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()
        if "bad pod line" in msg or "pod error" in msg or "unexpected pod line" in msg:
            self.lines.append(msg)


async def main() -> int:
    bad = BadLines()
    logging.getLogger("bench.pod").addHandler(bad)
    bus = EventBus(maxsize=200_000)
    events: list[tuple[float, str, object]] = []
    q = bus.subscribe()

    async def pump() -> None:
        while True:
            e = await q.get()
            events.append((time.monotonic(), e.kind, e.data))

    def samples(since: float = 0) -> list[dict]:
        return [d for t, k, d in events if k == ev.POD_SAMPLE and t >= since]

    async def wait(pred, timeout: float) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if pred():
                return True
            await asyncio.sleep(0.02)
        return pred()

    async def window(sec: float = 0.6) -> list[dict]:
        start = time.monotonic()
        await asyncio.sleep(sec)
        return samples(start)

    def mean(xs) -> float:
        xs = list(xs)
        return sum(xs) / len(xs) if xs else float("nan")

    pump_task = asyncio.create_task(pump())
    sim = Sim()
    while not os.path.exists(LINK):
        await asyncio.sleep(0.05)
    sim_start = time.monotonic()
    bridge = PodBridge(bus, LINK)
    bridge.start(asyncio.get_running_loop())
    try:
        # ---- #8 boot self-test, #6 connect ----
        ok = await wait(lambda: True in [d for _, k, d in events if k == ev.POD_STATUS], 5)
        check(ok, "bridge connects to the firmware", f"{time.monotonic() - sim_start:.2f} s")
        boot = [c for _, c in sim.leds()]
        check(boot[:4] == ["red", "green", "blue", "off"], "boot self-test: red → green → blue → off", str(boot[:4]))
        steps = [b - a for (a, _), (b, _) in zip(sim.leds()[:4], sim.leds()[1:4])]
        check(all(145 <= s <= 155 for s in steps), "…150 ms each", f"{steps} ms")

        # ---- #7 format + rate ----
        sim.cmd("Y 1900")
        sim.cmd("B 4987")
        sim.cmd("G 0")
        sim.cmd("W 3300")
        await asyncio.sleep(0.3)
        ss = await window(3.0)
        shape = all(
            set(s) == SAMPLE_KEYS
            and all(isinstance(s[k], int) for k in ("seq", "t", "vcc", "btn"))
            and all(len(s[k]) == 4 and all(isinstance(v, int) for v in s[k]) for k in ("mv", "lo", "hi"))
            and all(lo <= mv <= hi for lo, mv, hi in zip(s["lo"], s["mv"], s["hi"]))
            for s in ss
        )
        check(shape, "every sample: exact §2 keys, all ints, 4 probes, lo ≤ mv ≤ hi", f"{len(ss)} samples")
        check(all(b["seq"] == a["seq"] + 1 for a, b in zip(ss, ss[1:])), "seq +1 per line")
        dts = [b["t"] - a["t"] for a, b in zip(ss, ss[1:])]
        check(19 <= len(ss) / 3 <= 21 and set(dts) == {50}, "20 Hz, t steps exactly 50 ms",
              f"{len(ss) / 3:.1f} Hz, steps {sorted(set(dts))}")

        # ---- #7 test matrix (sim inputs; repeat on hardware) ----
        vcc = round(mean(s["vcc"] for s in ss))
        y, b, g, w = (round(mean(s["mv"][i] for s in ss)) for i in range(4))
        check(g < 20, "probe on GND → < 20 mV", f"G {g} mV")
        check(abs(b - vcc) <= 30, "probe on the 5 V rail → vcc ± 30 mV", f"B {b} mV, vcc {vcc} mV")
        check(abs(w - 3300) <= 40, "probe on 3.3 V → ≈3300 mV", f"W {w} mV")
        check(abs(y - 1900) <= 30, "LED anode 1.9 V → ≈1900 mV", f"Y {y} mV")
        sim.cmd(f"Y {4987 // 2}")
        await asyncio.sleep(0.2)
        mid = round(mean(s["mv"][0] for s in await window(0.5)))
        check(abs(mid - vcc / 2) <= 30, "10k/10k divider midpoint → ≈ vcc/2", f"{mid} mV vs {vcc / 2:.0f}")

        # ---- supply changes: vcc tracks it, readings stay right (ratiometric correction) ----
        sim.cmd("Y 1900")
        sim.cmd("vcc 4700")
        await asyncio.sleep(1.2)
        sw = await window(0.6)
        v2, y2 = round(mean(s["vcc"] for s in sw)), round(mean(s["mv"][0] for s in sw))
        check(abs(v2 - 4700) <= 30 and abs(y2 - 1900) <= 30, "supply sags to 4.70 V → vcc follows, Y still ≈1900",
              f"vcc {v2} mV, Y {y2} mV")
        sim.cmd("vcc 4987")

        # ---- #8 LED commands ----
        want = {"LED LISTEN": "green", "LED THINK": "blue", "LED SPEAK": "white", "LED ERROR": "red",
                "LED IDLE": "off"}
        for cmd, color in want.items():
            t0 = time.monotonic()
            await bridge.send(cmd)
            got = await wait(lambda: any(c == color for _, c in sim.leds(t0)), 1)
            check(got, f"{cmd} → LED {color}")

        # ---- #8 PING / unknown ----
        before = len(bad.lines)
        await bridge.send("FOO")
        check(await wait(lambda: any("unknown_cmd" in m for m in bad.lines[before:]), 1), "unknown command → err line")

        # ---- #8 button ----
        t0 = time.monotonic()
        sim.cmd("btn 400")
        await asyncio.sleep(0.8)
        evts = [d for t, k, d in events if t >= t0 and k == ev.POD_EVENT]
        ptt = [d for t, k, d in events if t >= t0 and k == ev.PTT]
        held = [s["btn"] for s in samples(t0)]
        down_ms = next((int(m[1]) for t, l in sim.out if t >= t0 and (m := re.match(r"\[\s*(\d+) ms\] button down", l))), None)
        lat = evts[0]["t"] - down_ms if evts and down_ms is not None else None
        check([e.get("down") for e in evts] == [1, 0] and all(set(e) == {"evt", "down", "t"} for e in evts),
              "button tap → evt down:1, then down:0", str(evts))
        check(lat is not None and lat <= 22, "press shows up within ~20 ms (debounce)", f"{lat} ms")
        check(ptt == [True, False], "bridge turns it into PTT start/stop", str(ptt))
        check(6 <= held.count(1) <= 10, "samples carry btn:1 while held", f"{held.count(1)} samples")

        t0 = time.monotonic()
        sim.cmd("bounce")
        await asyncio.sleep(0.8)
        evts = [d.get("down") for t, k, d in events if t >= t0 and k == ev.POD_EVENT]
        check(evts == [1, 0], "bouncy press (8 × 1 ms chatter) → exactly one down + one up", str(evts))

        # ---- reset (DTR on port open / brown-out) ----
        t0 = time.monotonic()
        last = samples()[-1]["seq"]
        sim.cmd("reset")
        ok = await wait(lambda: any(s["seq"] < 20 for s in samples(t0)) and bridge.connected, 6)
        hello = any(k == ev.POD_HELLO and t >= t0 for t, k, _ in events)
        check(ok and hello, "reset → self-test, hello, seq restarts, bridge stays/gets connected",
              f"seq {last} → 0, hello seen: {hello}")

        # ---- soak: every line parses ----
        before = len(bad.lines)
        t0 = time.monotonic()
        sim.cmd("W 2500")
        await asyncio.sleep(float(LONG))
        n = len(samples(t0))
        check(len(bad.lines) == before and 19 <= n / float(LONG) <= 21, f"{LONG} s soak: every line parses, still 20 Hz",
              f"{n} samples = {n / float(LONG):.2f} Hz, {len(bad.lines) - before} bad lines")
    finally:
        bridge.stop()
        sim.stop()
        pump_task.cancel()

    print(f"\n{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
