"""End-to-end check: tools/mock_pod.py talking to the real serial bridge (bench.pod.PodBridge, #16).

    cd server && uv run python tools/check_mock_pod.py

Starts the mock on a private symlink, connects PodBridge to it, drives the mock through its
console commands and checks what reaches the event bus. Covers #9's "Done when" (Y 10c → fault
led_reversed: ~1900 → ~5000 mV, fix → back) plus the rest of CONTRACTS §2–3. Exits 1 on any failure.
"""

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bench import bus as ev  # noqa: E402
from bench.bus import EventBus  # noqa: E402
from bench.pod import PodBridge  # noqa: E402

LINK = f"/tmp/bench-pod-check-{os.getpid()}"
MOCK = [sys.executable, str(Path(__file__).with_name("mock_pod.py")), "--link", LINK, "--seed", "7"]
SAMPLE_KEYS = {"seq", "t", "mv", "lo", "hi", "vcc", "btn"}

results: list[tuple[bool, str]] = []


def check(ok: bool, name: str, detail: str = "") -> bool:
    results.append((ok, name))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"   {detail}" if detail else ""), flush=True)
    return ok


class Mock:
    def __init__(self) -> None:
        self.proc = subprocess.Popen(MOCK, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, bufsize=1)
        self.out: list[str] = []
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        for line in self.proc.stdout:
            self.out.append(line.rstrip())

    def cmd(self, text: str) -> None:
        self.proc.stdin.write(text + "\n")
        self.proc.stdin.flush()

    def printed(self, needle: str) -> bool:
        return any(needle in line for line in self.out)

    def stop(self) -> None:
        self.proc.terminate()
        self.proc.wait(timeout=5)


class Rig:
    def __init__(self, bus: EventBus) -> None:
        self.events: list[tuple[float, str, object]] = []
        self.q = bus.subscribe()

    async def pump(self) -> None:
        while True:
            e = await self.q.get()
            self.events.append((time.monotonic(), e.kind, e.data))

    def samples(self, since: float = 0) -> list[dict]:
        return [d for t, k, d in self.events if k == ev.POD_SAMPLE and t >= since]

    async def wait(self, pred, timeout: float) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if pred():
                return True
            await asyncio.sleep(0.02)
        return pred()

    async def avg(self, probe: int = 0, n: int = 6, key: str = "mv") -> float:
        """Average of the next n samples for one probe."""
        start = time.monotonic()
        await self.wait(lambda: len(self.samples(start)) >= n, 3)
        vals = [s[key][probe] for s in self.samples(start)[:n]]
        return sum(vals) / len(vals) if vals else float("nan")

    def status(self) -> list[bool]:
        return [d for _, k, d in self.events if k == ev.POD_STATUS]


async def main() -> int:
    bus = EventBus(maxsize=100_000)
    rig = Rig(bus)
    pump = asyncio.create_task(rig.pump())
    mock = Mock()
    await asyncio.sleep(1.0)  # let the mock create its port + link
    bridge = PodBridge(bus, LINK)
    bridge.start(asyncio.get_running_loop())
    try:
        # 1 · connect
        t0 = time.monotonic()
        ok = await rig.wait(lambda: True in rig.status(), 4)
        check(ok, "bridge connects to the mock", f"{time.monotonic() - t0:.2f} s via {LINK}")
        if not ok:
            return 1

        # 2 · line shape + rate (CONTRACTS §2)
        start = time.monotonic()
        await asyncio.sleep(2.0)
        ss = rig.samples(start)
        shape_ok = all(
            set(s) == SAMPLE_KEYS
            and all(isinstance(s[k], int) for k in ("seq", "t", "vcc", "btn"))
            and all(len(s[k]) == 4 for k in ("mv", "lo", "hi"))
            and all(lo <= mv <= hi for lo, mv, hi in zip(s["lo"], s["mv"], s["hi"]))
            for s in ss
        )
        seq_ok = all(b["seq"] == a["seq"] + 1 for a, b in zip(ss, ss[1:]))
        dts = [b["t"] - a["t"] for a, b in zip(ss, ss[1:])]
        check(shape_ok, "every sample has exactly the §2 keys, ints, 4 probes, lo ≤ mv ≤ hi", f"{len(ss)} samples")
        check(seq_ok, "seq goes up by exactly 1 per line")
        check(18 <= len(ss) / 2.0 <= 22 and all(30 <= d <= 80 for d in dts),
              "20 Hz: one line every ~50 ms", f"{len(ss) / 2.0:.1f} Hz, t steps {min(dts)}–{max(dts)} ms")

        # 3 · #9 Done when: Y 10c → fault led_reversed → fix
        vcc = ss[-1]["vcc"]
        mock.cmd("Y 10c")
        y_ok = await rig.avg()
        check(abs(y_ok - 1900 * vcc / 5000) < 150, "Y in 10c reads the LED anode ≈1900 mV", f"{y_ok:.0f} mV")
        t_cmd = time.monotonic()
        mock.cmd("fault led_reversed")
        await rig.wait(lambda: any(s["mv"][0] > 4500 for s in rig.samples(t_cmd)), 2)
        lag = next((t for t, k, d in rig.events if k == ev.POD_SAMPLE and t >= t_cmd and d["mv"][0] > 4500), None)
        y_bad = await rig.avg()
        check(abs(y_bad - vcc) < 60, "fault led_reversed → Y ≈5000 mV",
              f"{y_bad:.0f} mV, {((lag or t_cmd) - t_cmd) * 1000:.0f} ms after the command")
        mock.cmd("fix")
        await asyncio.sleep(0.3)
        y_fixed = await rig.avg()
        check(abs(y_fixed - 1900 * vcc / 5000) < 150, "fix → Y back to ≈1900 mV", f"{y_fixed:.0f} mV")

        # 4 · laptop → pod commands (§3)
        await bridge.send("LED THINK")
        check(await rig.wait(lambda: mock.printed("LED THINK (blue)"), 1), "LED THINK reaches the mock")
        await bridge.send("FOO")
        check(await rig.wait(lambda: mock.printed("unknown command 'FOO'"), 1), "an unknown command gets err")

        # 5 · button → evt lines → PTT
        start = time.monotonic()
        mock.cmd("btn 0.4")
        await asyncio.sleep(0.8)
        evts = [d for t, k, d in rig.events if t >= start and k == ev.POD_EVENT]
        ptt = [d for t, k, d in rig.events if t >= start and k == ev.PTT]
        held = [s["btn"] for s in rig.samples(start)]
        check([e.get("down") for e in evts] == [1, 0] and all(set(e) == {"evt", "down", "t"} for e in evts),
              "button tap → evt down:1 then down:0", str(evts))
        check(ptt == [True, False], "…and the bridge turns them into PTT start/stop", str(ptt))
        check(5 <= held.count(1) <= 10, "samples show btn:1 while it's held", f"{held.count(1)} samples held")

        # 6 · unplugged probes
        mock.cmd("unplug Y -1")
        await asyncio.sleep(0.3)
        s = rig.samples()[-1]
        check(s["mv"][0] == s["lo"][0] == s["hi"][0] == -1, "unplug Y -1 → mv/lo/hi are -1", str(s["mv"]))
        mock.cmd("unplug Y")
        await asyncio.sleep(0.3)
        start = time.monotonic()
        await asyncio.sleep(0.5)
        spreads = [s["hi"][0] - s["lo"][0] for s in rig.samples(start)]
        spread = sum(spreads) / max(1, len(spreads))
        check(spread > 200, "unplug Y → floating: big lo–hi spread in every window", f"~{spread:.0f} mV")

        # 7 · Lab 2: the light sensor
        mock.cmd("lab lab2-light")
        await asyncio.sleep(0.3)
        room = await rig.avg()
        mock.cmd("light 0")
        await asyncio.sleep(0.2)
        dark = await rig.avg()
        mock.cmd("light 1")
        await asyncio.sleep(0.2)
        bright = await rig.avg()
        check(abs(room - 3571 * vcc / 5000) < 150 and dark < 1000 and bright > 4000,
              "lab2-light: Y in 30c follows the light", f"room {room:.0f} · covered {dark:.0f} · flashlight {bright:.0f} mV")
        mock.cmd("fault parts_swapped; light 0")
        await asyncio.sleep(0.3)
        swapped_dark = await rig.avg()
        check(swapped_dark > 4000, "parts_swapped: covering the sensor raises the output", f"{swapped_dark:.0f} mV")
        mock.cmd("lab lab1-led")

        # 8 · pod reboot (brown-out / DTR reset): garbage, ~1 s silence, hello, seq restarts.
        # The bridge may give up during the silence (SILENCE_S) and reopen, which can lose the hello;
        # either way it must end up connected with fresh readings.
        start = time.monotonic()
        last_seq = rig.samples()[-1]["seq"]
        mock.cmd("reset")
        ok = await rig.wait(lambda: any(s["seq"] < 20 for s in rig.samples(start)) and bridge.connected, 6)
        fresh = next((t for t, k, d in rig.events if k == ev.POD_SAMPLE and t >= start and d["seq"] < 20), None)
        hello = any(k == ev.POD_HELLO and t >= start for t, k, _ in rig.events)
        dropped = any(k == ev.POD_STATUS and d is False and t >= start for t, k, d in rig.events)
        check(ok, "reset → bridge recovers: seq restarts from 0, connected again",
              f"seq {last_seq} → 0, readings back after {((fresh or start) - start):.2f} s; "
              f"hello seen: {hello}; bridge dropped + reopened: {dropped}")

        # 9 · restart the mock on the same link (POD_PORT doesn't go stale)
        before = len(rig.status())
        mock.stop()
        mock = Mock()
        t0 = time.monotonic()
        ok = await rig.wait(lambda: rig.status()[before:].count(True) >= 1, 6)
        check(ok and False in rig.status()[before:], "mock restarted → bridge drops, then reconnects via the same link",
              f"{time.monotonic() - t0:.2f} s, status {rig.status()[before:]}")
        y = await rig.avg()
        check(abs(y - 1900 * vcc / 5000) < 150, "…and readings flow again", f"Y {y:.0f} mV")
    finally:
        bridge.stop()
        mock.stop()
        pump.cancel()

    failed = [n for ok, n in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed" + (f". Failed: {failed}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
