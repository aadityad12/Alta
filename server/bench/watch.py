"""Board watcher: ALTA looks at the board by itself once the student has worked on it and let go. No button.

Every POLL_S the server asks the student screen for a camera frame (the same silent request_frame that
look_at_board uses) and shrinks it to SMALL grey pixels. Hands over the board change a lot of pixels between
two frames ("motion"); camera noise and the camera re-adjusting its exposure don't. Once there's been motion,
then STILL_S without any, and ALTA has been idle for QUIET_S, it gets one `[event]` turn with the photo:
compare the board with the answer key, then point at a misplaced part (the wrong hole red, the right hole
green, an arrow between them) or stay silent. Silent looks are dropped from the conversation.

Work done while anyone was talking is ignored: that turn, or the probe monitor (#21), already covered it,
and a second reaction to the same move is exactly what the student shouldn't get. BENCH_WATCH=0 turns
the watcher off.
"""

import asyncio
import base64
import io
import itertools
import logging
import os
import time
from collections.abc import Callable

import numpy as np

from .protocol import PROBES, OverlayClearOut, State
from .tools import _downscale

log = logging.getLogger(__name__)

POLL_S = 1.0           # one frame a second
STILL_S = 3.0          # no motion for this long after work = the student let go
QUIET_S = 2.0          # ...and ALTA and the student have been quiet this long
MIN_GAP_S = 6.0        # at most one look this often
MAX_LOOKS = 60         # per student: a cap on what a busy table can cost
FRAME_TIMEOUT_S = 1.5  # the screen didn't answer: no camera right now
SMALL = (160, 120)     # motion is judged on a frame this small, in grey
PIX_T = 24.0           # a pixel "changed" if it moved more than this (0-255), after removing any exposure shift
MOTION_FRAC = 0.03     # ...and motion = more than this share of pixels changed. Measured on the phone camera:
                       # nothing moving 0.001-0.015, a hand over it 0.1-0.8
FLOATING_SPREAD_MV = 150  # a probe whose reading swings more than this in 50 ms isn't touching anything

NAMES = {"Y": "yellow", "B": "blue", "G": "green", "W": "white"}

LOOK = (
    "Board check: nobody asked, the server noticed that the student just worked on the board and has let go "
    "of it. The photo above is the camera's view, with row numbers and column letters drawn on it. Compare each "
    "part you can clearly see with its exact holes in the answer key. Parts for later steps that aren't on the "
    "board yet aren't mistakes, and ignore the pod's probe wires. "
    "If everything you can see is where it belongs, or you can't tell for sure from the photo, reply exactly "
    "<silent> and call no tools. "
    "If a part is clearly in the wrong place (wrong row or column, the LED in backwards, a wire in the wrong rail "
    "or missing from a step they've done), say so in one short sentence, then call highlight once with mode "
    "replace: the wrong hole as a hole with style bad, the right hole as a hole with style good, and an arrow from "
    "the wrong hole to the right one. If you're already walking the student through this fault with hints, stay "
    "at your hint level instead: a nudge or a question, the spot highlighted with style attention, and no good "
    "hole yet."
)


def enabled() -> bool:
    return os.environ.get("BENCH_WATCH", "1").strip().lower() not in ("0", "off", "no", "false")


def small_gray(jpeg: bytes) -> np.ndarray:
    """A camera JPEG -> SMALL grey pixels (float). draft() lets the JPEG decoder skip most of the work."""
    from PIL import Image

    img = Image.open(io.BytesIO(jpeg))
    img.draft("L", (SMALL[0] * 2, SMALL[1] * 2))
    return np.asarray(img.convert("L").resize(SMALL, Image.BILINEAR), dtype=np.float32)


def moved(a: np.ndarray, b: np.ndarray) -> float:
    """Share of pixels that changed between two frames, ignoring an overall brightness shift (exposure)."""
    d = b - a
    d -= d.mean()
    return float((np.abs(d) > PIX_T).mean())


class Activity:
    """When hands last moved over the board."""

    def __init__(self) -> None:
        self.prev: np.ndarray | None = None
        self.worked_at: float | None = None  # last motion not yet looked at

    def reset(self) -> None:
        self.prev = self.worked_at = None

    def feed(self, t: float, frame: np.ndarray) -> bool:
        """Returns True if this frame moved from the last one."""
        prev, self.prev = self.prev, frame
        if prev is None or prev.shape != frame.shape:
            return False
        if moved(prev, frame) > MOTION_FRAC:
            self.worked_at = t
            return True
        return False


class Watcher:
    def __init__(self, bench, agent, *, clock: Callable[[], float] = time.monotonic,
                 frame_timeout: float | None = None) -> None:
        self.bench = bench
        self.agent = agent
        self.clock = clock
        self.frame_timeout = FRAME_TIMEOUT_S if frame_timeout is None else frame_timeout
        self.activity = Activity()
        self.busy_at = float("-inf")  # last time anyone was talking or ALTA was busy
        self._busy_seen = bench.session.busy_count
        self.looked_at = float("-inf")
        self.looks = 0
        self.marked: int | None = None  # transcript length after a look that pointed at a mistake
        self._ids = itertools.count(1)
        self._gen = bench.session.generation

    async def run(self) -> None:
        log.info("board watcher on: ALTA looks %.0f s after the student lets go of the board (BENCH_WATCH=0: off)",
                 STILL_S)
        while True:
            await asyncio.sleep(POLL_S)
            try:
                await self.tick()
            except Exception:
                log.exception("watch: tick failed")

    async def tick(self) -> None:
        b, s = self.bench, self.bench.session
        if s.generation != self._gen:  # new student or new lab
            self._gen = s.generation
            self.activity.reset()
            self.looks, self.marked = 0, None
        self._note_busy()
        if not b.hub.clients or b.lab is None:
            self.activity.reset()
            return
        frame = await b.grab_frame(f"w{next(self._ids)}", self.frame_timeout)
        if frame is None:
            self.activity.reset()  # no camera right now: start over when it's back
            return
        try:
            jpeg = base64.b64decode(frame.jpeg_b64, validate=True)
            small = small_gray(jpeg)
        except Exception as e:
            log.warning("watch: unreadable frame: %r", e)
            self.activity.reset()
            return
        if s.generation != self._gen:
            return
        self._note_busy()
        now = self.clock()
        if self.activity.feed(now, small):
            log.debug("watch: motion")
        if self._ready(now):
            await self._look(jpeg)

    def _note_busy(self) -> None:
        s = self.bench.session
        if s.state is not State.idle or s.busy_count != self._busy_seen:  # busy now, or a turn came and went
            self._busy_seen = s.busy_count
            self.busy_at = self.clock()

    def _ready(self, now: float) -> bool:
        worked = self.activity.worked_at
        return (worked is not None and worked > self.busy_at  # work since anyone last talked
                and now - worked >= STILL_S - 1e-6
                and now - self.busy_at >= QUIET_S
                and now - self.looked_at >= MIN_GAP_S - 1e-6
                and self.looks < MAX_LOOKS
                and self.bench.session.state is State.idle)

    async def _look(self, jpeg: bytes) -> None:
        s = self.bench.session
        self.looks += 1
        self.looked_at = self.clock()
        self.activity.worked_at = None
        try:
            photo, w, h = _downscale(jpeg)
        except Exception as e:
            log.warning("watch: couldn't read the photo: %r", e)
            return
        log.info("watch: the student let go of the board: looking (%dx%d, look %d)", w, h, self.looks)
        s.record("watch", look=self.looks)
        tools = getattr(self.agent, "tools", None)
        if tools is not None:
            tools._save_frame(f"watch{self.looks}", photo)
        ran = getattr(self.agent, "turns_run", 0)
        said = await self.agent.turn(event=self._event(), images=[photo], forget_if_silent=True, frames=0)
        self._busy_seen = s.busy_count
        self.busy_at = self.clock()  # what the student did while ALTA looked was part of this look
        if getattr(self.agent, "turns_run", 1) == ran:
            return  # refused: someone started talking first. Nothing was looked at.
        if said:
            self.marked = len(s.transcript)
        elif self.marked is not None:
            if self.marked == len(s.transcript):  # nobody has spoken since ALTA marked the mistake: it's fixed
                await self.bench.hub.broadcast(OverlayClearOut())
            self.marked = None

    def _event(self) -> str:
        s = self.bench.session
        parts = [LOOK, f"The student is on manual step {s.step}."]
        if probes := self._probes():
            parts.append(f"Probes right now: {probes}.")
        return " ".join(parts)

    def _probes(self) -> str | None:
        p = self.bench.session.probes
        if not p:
            return None
        out = []
        for i, name in enumerate(PROBES):
            mv, lo, hi = p["mv"][i], p.get("lo", p["mv"])[i], p.get("hi", p["mv"])[i]
            if mv < 0:
                out.append(f"{NAMES[name]} unplugged")
            elif hi - lo > FLOATING_SPREAD_MV:
                out.append(f"{NAMES[name]} floating (not touching anything)")
            else:
                out.append(f"{NAMES[name]} {mv} mV")
        return ", ".join(out)
