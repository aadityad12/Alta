"""Serial bridge to the pod (real Uno or the mock pod from #9). Protocol: CONTRACTS §2–3.

A reader thread owns the port: it finds it, opens it, waits for `hello`, parses one JSON object per
line and publishes it on the bus. If the pod is unplugged or goes quiet it retries until it's back.
"""

import asyncio
import glob
import json
import logging
import os
import threading
import time
from typing import Any

import serial

from . import bus as ev
from .bus import Event, EventBus

log = logging.getLogger(__name__)

BAUD = 115200
AUTODETECT = ["/dev/cu.usbmodem*", "/dev/cu.usbserial*", "/dev/cu.wchusbserial*", "/dev/ttyACM*", "/dev/ttyUSB*"]
HELLO_TIMEOUT_S = 3.0  # opening the port resets the Uno; it says hello when it's booted
SILENCE_S = 2.0        # 20 lines a second, so this much quiet means it's gone. Over the Uno's ~1 s reboot
                       # (brown-out), so we ride it out instead of reopening the port, which resets it again.
RETRY_S = 0.5          # retry this often while the pod is missing (recovers well inside 2 s)
OFF = {"off", "none", "0"}
LED_COMMANDS = {"LED IDLE", "LED LISTEN", "LED THINK", "LED SPEAK", "LED ERROR"}  # CONTRACTS §3


class PodBridge:
    def __init__(self, bus: EventBus, port: str | None = None) -> None:
        self.bus = bus
        self.port = port  # None = auto-detect
        self.connected = False
        self._ser: serial.Serial | None = None
        self._write_lock = threading.Lock()
        self._last_led: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._bad_lines = 0

    # ---------- lifecycle ----------

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._thread = threading.Thread(target=self._run, name="pod-reader", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    # ---------- laptop -> pod ----------

    async def send(self, cmd: str) -> None:
        """Send a command line (`LED THINK`, `PING`, …). LED commands are remembered and replayed on reconnect."""
        if cmd in LED_COMMANDS:
            self._last_led = cmd
        if self.connected:
            await asyncio.to_thread(self._write, cmd)

    def _write(self, cmd: str) -> None:
        ser = self._ser
        if ser is None:
            return
        try:
            with self._write_lock:
                ser.write(f"{cmd}\n".encode())
        except (serial.SerialException, OSError) as e:
            log.warning("pod write failed (%s); the reader will reconnect", e)

    # ---------- reader thread ----------

    def _publish(self, kind: str, data: Any) -> None:
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self.bus.publish, Event(kind, data))

    def _find_port(self) -> str | None:
        if self.port:
            return self.port if os.path.exists(self.port) else None
        found = sorted(p for pattern in AUTODETECT for p in glob.glob(pattern))
        return found[0] if found else None

    def _run(self) -> None:
        missing_logged = False
        while not self._stop.is_set():
            port = self._find_port()
            if port is None:
                if not missing_logged:
                    log.info("no pod found (%s); plug it in or set POD_PORT. Retrying.", self.port or "auto-detect")
                    missing_logged = True
                self._stop.wait(RETRY_S)
                continue
            try:
                self._ser = serial.Serial(port, BAUD, timeout=0.05, write_timeout=0.5)
            except (serial.SerialException, OSError) as e:
                log.debug("can't open %s: %s", port, e)
                self._stop.wait(RETRY_S)
                continue
            missing_logged = False
            log.info("pod port open: %s", port)
            try:
                self._read_loop()
            except (serial.SerialException, OSError) as e:
                log.warning("pod connection lost: %s", e)
            finally:
                self._close()
            self._stop.wait(RETRY_S)

    def _read_loop(self) -> None:
        ser = self._ser
        opened = last_rx = time.monotonic()
        got_data = pinged = False
        first = True  # we probably opened mid-line; that first fragment isn't worth a warning
        buf = b""
        while not self._stop.is_set():
            chunk = ser.read(ser.in_waiting or 1)
            now = time.monotonic()
            if chunk:
                last_rx = now
                buf += chunk
                *lines, buf = buf.split(b"\n")
                if first and lines:
                    first = False
                    if not lines[0].lstrip().startswith(b"{"):
                        lines = lines[1:]
                for raw in lines:
                    msg = self._parse(raw)
                    if msg is None:
                        continue
                    got_data = True
                    if "hello" in msg:
                        log.info("pod says hello: fw %s", msg.get("fw"))
                        self._publish(ev.POD_HELLO, msg)
                        self._set_connected()
                    elif "pong" in msg:
                        self._set_connected()
                    else:
                        self._dispatch(msg)
                        if not self.connected and not pinged:
                            # Readings but no hello: the pod was already running (no reset on open, or we
                            # missed its hello). It's past booting, so it's safe to ask whether it's there.
                            pinged = True
                            self._write("PING")
            if self.connected:
                if now - last_rx > SILENCE_S:
                    raise serial.SerialException(f"no data for {SILENCE_S:.0f} s")
            elif now - opened > HELLO_TIMEOUT_S:
                if not got_data:
                    raise serial.SerialException(f"no data within {HELLO_TIMEOUT_S:.0f} s of opening")
                log.info("no hello or pong, but the pod is talking; treating it as connected")
                self._set_connected()

    def _parse(self, raw: bytes) -> dict[str, Any] | None:
        text = raw.strip().decode("utf-8", "replace")
        if not text:
            return None
        try:
            msg = json.loads(text)
            if not isinstance(msg, dict):
                raise ValueError("not an object")
            if "mv" in msg and not _is_sample(msg):
                raise ValueError("bad sample")
            return msg
        except ValueError:
            self._bad_lines += 1
            if self._bad_lines <= 10 or self._bad_lines % 100 == 0:
                log.warning("bad pod line #%d: %r", self._bad_lines, text[:120])
            return None

    def _dispatch(self, msg: dict[str, Any]) -> None:
        if "mv" in msg:
            self._publish(ev.POD_SAMPLE, msg)
        elif msg.get("evt") == "btn":
            self._publish(ev.POD_EVENT, msg)
            self._publish(ev.PTT, bool(msg.get("down")))
        elif "evt" in msg:
            self._publish(ev.POD_EVENT, msg)
        elif "err" in msg:
            log.warning("pod error: %s", msg["err"])
        else:
            log.warning("unexpected pod line: %s", msg)

    def _set_connected(self) -> None:
        if self.connected:
            return
        self.connected = True
        self._publish(ev.POD_STATUS, True)
        if self._last_led:  # put the LED back to Bench's current state
            self._write(self._last_led)

    def _close(self) -> None:
        was_connected, self.connected = self.connected, False
        ser, self._ser = self._ser, None
        try:
            if ser:
                ser.close()
        except Exception:
            pass
        if was_connected:
            self._publish(ev.POD_STATUS, False)


def _is_sample(msg: dict[str, Any]) -> bool:
    return all(
        isinstance(msg.get(k), list) and len(msg[k]) == 4 and all(isinstance(v, int) for v in msg[k])
        for k in ("mv", "lo", "hi")
    )
