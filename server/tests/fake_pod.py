"""Minimal stand-in pod for tests: speaks CONTRACTS §2–3 on a pseudo-terminal.

Not the mock pod from #9 (server/tools/mock_pod.py, Engineer A's): no labs, no faults, just the protocol.
The bridge opens a stable symlink, so "replugging" means a new pty behind the same path, like a real Uno.
"""

import json
import os
import select
import threading
import time
import tty


class FakePod:
    def __init__(self, link: str, *, mv=(5000, 1900, 2, 3)) -> None:
        self.link = link
        self.hello = True
        self.boot_s = 0.0  # > 0: act like an Uno that resets on open (silent, then hello, then samples)
        self.answers_ping = True
        self.paused = False  # True: stop sending samples (a reboot or brown-out), but stay plugged in
        self.mv = list(mv)
        self.btn = 0
        self.commands: list[str] = []
        self._master: int | None = None
        self._slave: int | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def plug(self) -> None:
        self._master, self._slave = os.openpty()
        tty.setraw(self._slave)
        tmp = self.link + ".tmp"
        if os.path.lexists(tmp):
            os.unlink(tmp)
        os.symlink(os.ttyname(self._slave), tmp)
        os.replace(tmp, self.link)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def unplug(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        for fd in (self._master, self._slave):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        self._master = self._slave = None
        if os.path.lexists(self.link):
            os.unlink(self.link)

    def write_raw(self, data: bytes) -> None:
        with self._lock:
            if self._master is not None:
                os.write(self._master, data)

    def send(self, obj: dict) -> None:
        self.write_raw((json.dumps(obj) + "\n").encode())

    def press(self, down: bool) -> None:
        self.btn = int(down)
        self.send({"evt": "btn", "down": self.btn, "t": int(time.monotonic() * 1000)})

    def leds(self) -> list[str]:
        return [c for c in self.commands if c.startswith("LED ")]

    def _run(self) -> None:
        if self.boot_s and self._stop.wait(self.boot_s):
            return
        if self.hello:
            self.send({"hello": "bench-pod", "fw": "0.1.0", "probes": ["Y", "B", "G", "W"]})
        seq, buf, next_sample = 0, b"", time.monotonic()
        while not self._stop.is_set():
            r, _, _ = select.select([self._master], [], [], 0.01)
            if r:
                try:
                    buf += os.read(self._master, 1024)
                except OSError:
                    return
                *lines, buf = buf.split(b"\n")
                for line in lines:
                    cmd = line.decode().strip()
                    self.commands.append(cmd)
                    if cmd == "PING" and self.answers_ping:
                        self.send({"pong": 1, "fw": "0.1.0"})
                    elif cmd != "PING" and not cmd.startswith("LED "):
                        self.send({"err": "unknown_cmd"})
            if self.paused:
                next_sample = time.monotonic()
            elif time.monotonic() >= next_sample:
                next_sample += 0.05
                self.send({"seq": seq, "t": seq * 50, "mv": self.mv, "lo": [v - 5 for v in self.mv],
                           "hi": [v + 5 for v in self.mv], "vcc": 4987, "btn": self.btn})
                seq += 1
