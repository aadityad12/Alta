"""Mock probe pod (#9): a fake pod on a virtual serial port, speaking exactly CONTRACTS §2–3.

Run it (from server/), leave it open, and point the server at it:

    uv run python tools/mock_pod.py                         # Lab 1, correct circuit, yellow probe in 10c
    uv run python tools/mock_pod.py --lab lab2-light
    uv run python tools/mock_pod.py --scenario led_reversed --cmd "B 13c"

    POD_PORT=/tmp/bench-pod scripts/dev.sh                  # or put POD_PORT=/tmp/bench-pod in .env

/tmp/bench-pod is a symlink to the virtual port (/dev/ttysNNN). The link stays the same when you
restart the mock, so POD_PORT never goes stale.

Commands (type them here, pass them with --cmd, or pipe them on stdin):
    Y 10c           plug the yellow probe into hole 10c (B, G, W the same; strips and rails work too)
    unplug Y        that probe floats (random noise);  unplug Y -1 → it reads -1;  unplug all
    fault <id>      stage a fault from lab.yaml (+ its scenarios/<id>.yaml);  fix → correct circuit
    lab <id>        switch lab (probes move to that lab's starting holes);  labs / faults list them
    light 0..1      Lab 2 light level: 0 covered · 0.5 room · 1 flashlight
    btn             tap the talk button (0.3 s);  btn 2.5 → hold 2.5 s;  btn down / btn up
    reset           reboot like a real Uno: a garbage line, ~1 s deaf, then hello; seq and t restart at 0
    sleep 1.5       delay the commands after it (handy in --cmd scripts)
    status · help · quit

How a probe's voltage is worked out (format: labs/README.md): find the net that contains the
probe's hole, then apply in order: the net's expected_mv → the active fault's readings → the
scenario's light model → the scenario's nets: overrides. Holes in no net read the scenario's holes:
entry, or float. Values are scaled by vcc the way the real ADC is.
"""

import argparse
import collections
import importlib.util
import json
import os
import random
import select
import signal
import sys
import termios
import time
import tty
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
LABS_DIR = REPO / "labs"

# Hole parsing and the photoresistor model live in labs/validate.py, so the lab files, their
# validator and this mock can't disagree about them.
_spec = importlib.util.spec_from_file_location("bench_lab_validate", LABS_DIR / "validate.py")
_labcheck = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_labcheck)
node_of = _labcheck.node_of
light_mv = _labcheck.light_mv

FW = "0.1.0-mock"
PROBES = ("Y", "B", "G", "W")
TICK_S = 0.05            # one sample line every 50 ms (20 Hz)
SUBSAMPLES = 10          # ADC reads per 50 ms window → mv (mean), lo (min), hi (max)
NOISE_MV = 5             # default ±noise on a connected net
VCC_MV = 4987            # USB 5 V as the Uno sees it
BOOT_S = 1.0             # `reset`: how long the Uno is deaf (bootloader) before hello
TAP_S = 0.3
LEDS = {"IDLE": ("off", "2"), "LISTEN": ("green", "92"), "THINK": ("blue", "94"),
        "SPEAK": ("white", "97"), "ERROR": ("red", "91")}


def say(msg: str) -> None:
    print(msg, flush=True)


class MockPod:
    def __init__(self, labs_dir: Path, link: str | None, seed: int | None):
        self.labs_dir = labs_dir
        self.rng = random.Random(seed)
        self.master, self.slave = os.openpty()
        tty.setraw(self.slave)                      # no echo, no line editing: a plain byte pipe
        os.set_blocking(self.master, False)
        self.device = os.ttyname(self.slave)
        self.link = self._make_link(link) if link else None

        self.boot_t0 = time.monotonic()
        self.seq = 0
        self.booting_until: float | None = None
        self.btn = 0
        self.btn_release_at: float | None = None
        self.led = "IDLE"
        self.rx = b""
        self.dropped = 0
        self.light = 0.5
        self.float_mv = {p: self.rng.uniform(1000, 4000) for p in PROBES}
        self.unplug_mode = {p: "noise" for p in PROBES}
        self.queue: collections.deque[tuple[float, str]] = collections.deque()

    # ---------- setup ----------

    def _make_link(self, link: str) -> str | None:
        if os.path.islink(link):
            os.remove(link)
        elif os.path.exists(link):
            say(f"! {link} exists and isn't a symlink; not touching it. Use POD_PORT={self.device}")
            return None
        os.symlink(self.device, link)
        return link

    def close(self) -> None:
        if self.link and os.path.islink(self.link) and os.readlink(self.link) == self.device:
            os.remove(self.link)

    def load_lab(self, lab_id: str, scenario: str = "normal") -> None:
        path = self.labs_dir / lab_id / "lab.yaml"
        if not path.exists():
            say(f"! no lab {lab_id!r}. Labs: {', '.join(self.lab_ids())}")
            return
        self.lab = yaml.safe_load(path.read_text())
        self.lab_id = lab_id
        self.nets = {n["id"]: n for n in self.lab["nets"]}
        self.node_net = {node_of(h): n["id"] for n in self.lab["nets"] for h in n["holes"]}
        self.faults = {f["id"]: f for f in self.lab["faults"]}
        self.light = 0.5
        self.probes: dict[str, str | None] = {p: None for p in PROBES}
        self.set_scenario(scenario, move_probes=True)

    def lab_ids(self) -> list[str]:
        return sorted(p.parent.name for p in self.labs_dir.glob("*/lab.yaml"))

    def set_scenario(self, name: str, move_probes: bool = False) -> bool:
        if name != "normal" and name not in self.faults:
            say(f"! no fault {name!r} in {self.lab_id}. Faults: {', '.join(self.faults)}")
            return False
        path = self.labs_dir / self.lab_id / "scenarios" / f"{name}.yaml"
        self.scen = yaml.safe_load(path.read_text()) if path.exists() else {"fault": None if name == "normal" else name}
        self.fault = self.faults.get(self.scen.get("fault") or "")
        self.hole_over = {node_of(h): o for h, o in (self.scen.get("holes") or {}).items()}
        if move_probes:
            for p, hole in (self.scen.get("probes") or {}).items():
                self.probes[p] = hole
        return True

    # ---------- the voltages ----------

    def target_at(self, hole: str) -> tuple[int, int] | None:
        """(mV at a 5.000 V supply, ±noise) for whatever is plugged in at `hole`; None = floating."""
        node = node_of(hole)
        net_id = self.node_net.get(node)
        if net_id:
            mv = self.nets[net_id]["expected_mv"]
            if self.fault:
                mv = self.fault["readings"].get(net_id, mv)
            lm = self.scen.get("light_model")
            if lm and lm["net"] == net_id:
                mv = light_mv(lm, self.lab["supply_mv"], self.light)
            o = (self.scen.get("nets") or {}).get(net_id, {})
            return o.get("mv", mv), o.get("noise_mv", NOISE_MV)
        if node in self.hole_over:
            o = self.hole_over[node]
            return o["mv"], o.get("noise_mv", NOISE_MV)
        return None

    def reading(self, probe: str, vcc: int) -> tuple[int, int, int]:
        """(mv, lo, hi) over one 50 ms window, like the firmware: SUBSAMPLES reads, mean/min/max."""
        hole = self.probes[probe]
        target = self.target_at(hole) if hole else None
        if target is None:
            if hole is None and self.unplug_mode[probe] == "-1":
                return -1, -1, -1
            # Floating input: wanders around and is noisy within the window too.
            f = self.float_mv[probe] = min(vcc, max(0, self.float_mv[probe] + self.rng.gauss(0, 250)))
            center, noise = f, 300
        else:
            mv, noise = target
            center = mv * vcc / self.lab["supply_mv"]   # the ADC measures relative to the pod's own 5 V
        reads = [min(vcc, max(0, center + self.rng.uniform(-noise, noise))) for _ in range(SUBSAMPLES)]
        return round(sum(reads) / len(reads)), round(min(reads)), round(max(reads))

    # ---------- serial out ----------

    def t_ms(self) -> int:
        return max(0, int((time.monotonic() - self.boot_t0) * 1000))

    def send(self, obj: dict) -> None:
        self.write((json.dumps(obj, separators=(",", ":")) + "\n").encode())

    def write(self, data: bytes) -> None:
        try:
            while data:
                data = data[os.write(self.master, data):]
        except BlockingIOError:
            # Nobody is reading and the port's buffer is full. Like a real pod streaming into a
            # closed port: drop it, and flush the stale backlog so a new reader gets fresh lines.
            self.dropped += 1
            termios.tcflush(self.slave, termios.TCIFLUSH)

    def hello(self) -> None:
        # Leading \n: if a reboot cut a line off mid-way, end it here so it can't swallow the hello.
        self.write(b"\n")
        self.send({"hello": "bench-pod", "fw": FW, "probes": list(PROBES)})

    def sample(self, tick: float) -> None:
        """One sample line. `t` is the tick's scheduled time, so it steps a steady 50 ms like the
        firmware's timer even when this process is briefly late."""
        vcc = VCC_MV + self.rng.randint(-3, 3)
        r = [self.reading(p, vcc) for p in PROBES]
        self.send({"seq": self.seq, "t": max(0, int((tick - self.boot_t0) * 1000)),
                   "mv": [x[0] for x in r], "lo": [x[1] for x in r], "hi": [x[2] for x in r],
                   "vcc": vcc, "btn": self.btn})
        self.seq += 1

    def press(self, release_after: float | None) -> None:
        if not self.btn:
            self.btn = 1
            self.send({"evt": "btn", "down": 1, "t": self.t_ms()})
            say("  button down")
        self.btn_release_at = None if release_after is None else time.monotonic() + release_after

    def release(self) -> None:
        self.btn_release_at = None
        if self.btn:
            self.btn = 0
            self.send({"evt": "btn", "down": 0, "t": self.t_ms()})
            say("  button up")

    # ---------- serial in (laptop → pod) ----------

    def read_serial(self) -> None:
        try:
            self.rx += os.read(self.master, 1024)
        except (BlockingIOError, OSError):
            return
        *lines, self.rx = self.rx.split(b"\n")
        for raw in lines:
            cmd = raw.decode("ascii", "replace").strip()
            if not cmd:
                continue
            if self.booting_until:
                say(f"  (booting, ignored {cmd!r})")
            elif cmd == "PING":
                self.send({"pong": 1, "fw": FW})
                say("  PING → pong")
            elif cmd.startswith("LED ") and cmd[4:] in LEDS:
                self.led = cmd[4:]
                color, ansi = LEDS[self.led]
                say(f"\033[{ansi}m●\033[0m LED {self.led} ({color})")
            else:
                self.send({"err": "unknown_cmd"})
                say(f"  unknown command {cmd!r} → err")

    # ---------- console commands ----------

    def queue_cmds(self, text: str) -> None:
        due = max([time.monotonic()] + [d for d, _ in self.queue])
        for cmd in (c.strip() for c in text.replace(";", "\n").splitlines()):
            if not cmd:
                continue
            parts = cmd.split()
            if parts[0] == "sleep" and len(parts) == 2:
                due += float(parts[1])
            else:
                self.queue.append((due, cmd))

    def run_due_cmds(self, now: float) -> None:
        while self.queue and self.queue[0][0] <= now:
            _, cmd = self.queue.popleft()
            try:
                self.command(cmd)
            except (ValueError, IndexError) as e:
                say(f"! couldn't run {cmd!r}: {e}. Type help.")

    def command(self, cmd: str) -> None:
        parts = cmd.split()
        head = parts[0].lower()
        if head.upper() in PROBES and len(parts) == 2:
            p, hole = head.upper(), parts[1]
            if node_of(hole) is None:
                raise ValueError(f"{hole!r} isn't a hole (10c), strip (10:a-e) or rail (rail:a+)")
            self.probes[p] = hole
            say(f"  {p} → {hole}: {self.describe(p)}")
        elif head == "unplug":
            which = PROBES if parts[1].lower() == "all" else (parts[1].upper(),)
            for p in which:
                self.probes[p] = None
                self.unplug_mode[p] = "-1" if parts[2:] == ["-1"] else "noise"
            say(f"  unplugged {', '.join(which)} ({'reads -1' if parts[2:] == ['-1'] else 'floating'})")
        elif head == "fault":
            if self.set_scenario(parts[1]):
                say(f"  fault on: {self.fault['name']} ({self.fault['id']})")
        elif head == "fix":
            self.set_scenario("normal")
            say("  fixed: correct circuit")
        elif head == "lab":
            self.load_lab(parts[1])
            say(f"  {self.banner_line()}")
        elif head == "labs":
            say("  " + ", ".join(self.lab_ids()))
        elif head == "faults":
            for f in self.faults.values():
                say(f"  {f['id']:<24} {f['name']}")
        elif head == "light":
            self.light = min(1.0, max(0.0, float(parts[1])))
            lm = self.scen.get("light_model")
            say(f"  light = {self.light:.2f}" + ("" if lm else "  (nothing in this lab/fault reacts to light)"))
        elif head == "btn":
            arg = parts[1].lower() if len(parts) > 1 else None
            if arg == "down":
                self.press(None)
            elif arg == "up":
                self.release()
            else:
                self.press(float(arg) if arg else TAP_S)
        elif head == "reset":
            self.reset()
        elif head == "status":
            self.status()
        elif head in ("help", "?"):
            say(__doc__.split("Commands")[1].split("How a probe")[0].rstrip())
        elif head in ("quit", "exit"):
            raise SystemExit(0)
        else:
            raise ValueError("unknown command")

    def reset(self) -> None:
        """Like the Uno rebooting (DTR reset, brown-out): noise, deaf while booting, then hello."""
        say("  rebooting…")
        self.write(b'\x00\xf0{"seq":' + str(self.seq).encode())  # cut-off line + bootloader garbage
        self.btn, self.btn_release_at, self.led = 0, None, "IDLE"
        self.booting_until = time.monotonic() + BOOT_S
        self.boot_t0 = self.booting_until
        self.seq = 0

    def describe(self, p: str) -> str:
        hole = self.probes[p]
        if hole is None:
            return "unplugged"
        net_id = self.node_net.get(node_of(hole))
        mv = self.reading(p, VCC_MV)[0]
        where = self.nets[net_id]["label"] if net_id else ("not on any net" if self.target_at(hole) else "floating")
        return f"{where}, ≈{mv} mV"

    def status(self) -> None:
        say(f"  {self.banner_line()} · light {self.light:.2f} · LED {self.led} · btn {self.btn}"
            + (f" · {self.dropped} lines dropped (no reader)" if self.dropped else ""))
        for p in PROBES:
            say(f"  {p}: {self.probes[p] or '-':<8} {self.describe(p)}")

    def banner_line(self) -> str:
        fault = f"fault {self.fault['id']}" if self.fault else "correct circuit"
        return f"{self.lab_id} ({self.lab['title']}) · {fault}"

    # ---------- main loop ----------

    def run(self) -> None:
        self.hello()
        stdin_fd = sys.stdin.fileno()
        stdin_buf = b""
        next_tick = time.monotonic()
        while True:
            now = time.monotonic()
            wake = [next_tick] + [d for d, _ in list(self.queue)[:1]]
            wake += [t for t in (self.btn_release_at, self.booting_until) if t]
            fds = [self.master] + ([stdin_fd] if stdin_fd is not None else [])
            ready, _, _ = select.select(fds, [], [], max(0.0, min(wake) - now))
            if self.master in ready:
                self.read_serial()
            if stdin_fd is not None and stdin_fd in ready:
                # Raw reads, not readline(): several commands can arrive at once, and a buffered
                # readline() would leave the rest stuck where select() can't see them.
                chunk = os.read(stdin_fd, 4096)
                if chunk:
                    *lines, stdin_buf = (stdin_buf + chunk).split(b"\n")
                    for line in lines:
                        self.queue_cmds(line.decode(errors="replace"))
                else:
                    stdin_fd = None         # piped input ended; keep streaming until Ctrl-C
            now = time.monotonic()
            self.run_due_cmds(now)
            if self.btn_release_at and now >= self.btn_release_at:
                self.release()
            if self.booting_until and now >= self.booting_until:
                self.booting_until = None
                self.hello()
                say("  booted, hello sent")
            if now >= next_tick:
                if not self.booting_until:
                    self.sample(next_tick)
                next_tick += TICK_S
                if next_tick < now - 0.5:   # we were stalled (laptop asleep?); don't burst-catch-up
                    next_tick = now + TICK_S


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lab", default="lab1-led")
    ap.add_argument("--scenario", default="normal", help="normal, or a fault id from the lab")
    ap.add_argument("--cmd", action="append", default=[], help="run a command at start (repeatable; ';' separates)")
    ap.add_argument("--link", default="/tmp/bench-pod", help="stable symlink to the port ('' = none)")
    ap.add_argument("--labs-dir", type=Path, default=LABS_DIR)
    ap.add_argument("--seed", type=int, help="fixed random seed (repeatable noise for tests)")
    args = ap.parse_args()

    pod = MockPod(args.labs_dir, args.link or None, args.seed)
    for sig in (signal.SIGTERM, signal.SIGHUP):          # killed or terminal closed: still remove the link
        signal.signal(sig, lambda *_: sys.exit(0))
    try:
        pod.load_lab(args.lab, args.scenario)
        if not hasattr(pod, "lab"):
            return 1
        port = pod.link or pod.device
        say(f"Mock pod on {pod.device}" + (f"  (link: {pod.link})" if pod.link else ""))
        say(f"  → run the server with POD_PORT={port}   (or put it in .env)")
        say(f"  {pod.banner_line()}")
        for p in PROBES:
            if pod.probes[p]:
                say(f"  {p} → {pod.probes[p]}: {pod.describe(p)}")
        say("  Type help for commands, Ctrl-C to stop.")
        for c in args.cmd:
            pod.queue_cmds(c)
        pod.run()
    except KeyboardInterrupt:
        pass
    finally:
        pod.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
