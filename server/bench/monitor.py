"""Probe monitor (#21): tell the agent when a probe it asked for lands and settles, or when a fault gets
fixed, so Bench reacts with no button press.

Only probes with a pending `expect` (from ask_for_probe) are watched. For each one, the last STEADY_S of
readings has to hold within ±STEADY_MV, with a quiet lo–hi spread in every 50 ms window ("steady"). A
steady reading is reported once, if it's news:
- the first steady reading since the probe was out (floating or unplugged), or
- it moved more than MOVE_MV from the last one, or crossed into / out of the expected band, or
- the probe was out of place for a while (moved to another hole) and this expect hasn't been answered yet.
Contact bounce while plugging never holds steady, so it's never reported; a jiggle that comes back to the
same value isn't news.

Events wait while anyone is talking or Bench is busy (any state but idle), and go out together as one
`[event]` turn when Bench is idle again. A newer event for a probe replaces its older one; anything older
than MAX_AGE_S is dropped.
"""

import collections
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from . import bus as ev
from .bus import Event
from .protocol import PROBES, ExpectOut, State

log = logging.getLogger(__name__)

STEADY_S = 0.5      # how long a reading has to hold to count as plugged in
STEADY_MV = 30      # ...within ± this
SPREAD_MV = 150     # ...with no 50 ms window noisier than this (a floating wire picks up hum)
MOVE_MV = 150       # a change bigger than this is a new reading
BAND_MOVE_MV = 60   # crossing the expected band counts if it moved at least this (no flapping at the edge)
AWAY_SAMPLES = 5    # out of place this many samples (250 ms): the probe was moved, not just jiggled
GAP_S = 0.25        # no sample for this long (reboot, replug): start the window over
MAX_AGE_S = 10.0    # undelivered events older than this are stale

NAMES = {"Y": "Yellow", "B": "Blue", "G": "Green", "W": "White"}


@dataclass
class ProbeEvent:
    probe: str
    mv: int
    kind: str  # "reading" (landed or changed) or "fixed" (out of the expected band -> into it)
    text: str

    def __str__(self) -> str:
        return self.text


class Window:
    """One probe's readings over the last STEADY_S."""

    def __init__(self) -> None:
        self.samples: collections.deque[tuple[float, int, int]] = collections.deque()  # (t, mv, hi - lo)

    def feed(self, t: float, mv: int, lo: int, hi: int) -> None:
        if self.samples and t - self.samples[-1][0] > GAP_S:
            self.samples.clear()
        self.samples.append((t, mv, hi - lo))
        while len(self.samples) > 1 and self.samples[1][0] <= t - STEADY_S:
            self.samples.popleft()

    def steady(self) -> int | None:
        """The average reading if the probe has held still for STEADY_S, else None."""
        if not self.samples or self.samples[-1][0] - self.samples[0][0] < STEADY_S - 1e-6:
            return None
        mvs = [mv for _, mv, _ in self.samples]
        if min(mvs) < 0 or max(mvs) - min(mvs) > 2 * STEADY_MV:
            return None
        if max(spread for _, _, spread in self.samples) > SPREAD_MV:
            return None
        return round(sum(mvs) / len(mvs))


class Detector:
    """Decides which steady readings of one requested probe are worth telling the agent about."""

    def __init__(self, expect: ExpectOut, steady_now: int | None) -> None:
        self.expect = expect
        self.last = steady_now  # where the probe sat when it was asked for (None: it was out)
        self.last_in_band = self.in_band(steady_now)
        self.away = 0
        self.answered = False  # reported anything for this request yet?

    def in_band(self, mv: int | None) -> bool | None:
        e = self.expect
        if mv is None or e.expected_mv is None or e.tol_mv is None:
            return None
        return abs(mv - e.expected_mv) <= e.tol_mv

    def update(self, mv: int, steady: int | None) -> ProbeEvent | None:
        if self.last is not None and (mv < 0 or abs(mv - self.last) > MOVE_MV):
            self.away += 1
        if steady is None:
            return None
        in_band = self.in_band(steady)
        moved = self.last is None or abs(steady - self.last) > MOVE_MV
        crossed = self.last is not None and in_band != self.last_in_band and abs(steady - self.last) >= BAND_MOVE_MV
        replugged = self.away >= AWAY_SAMPLES and not self.answered
        self.away = 0
        if not (moved or crossed or replugged):
            return None
        # Fixed = this request already read out of range, and now it's in. Before the first answer, `last`
        # is wherever the probe sat before it was moved here, so it says nothing about a fix.
        fixed = bool(in_band) and self.last_in_band is False and self.answered
        before = self.last
        self.last, self.last_in_band, self.answered = steady, in_band, True
        return self._event(steady, in_band, before, fixed)

    def _event(self, mv: int, in_band: bool | None, before: int | None, fixed: bool) -> ProbeEvent:
        e = self.expect
        who = f"{NAMES[e.probe]} probe (asked for {e.at}" + (f", {e.label})" if e.label else ")")
        if in_band is None:
            return ProbeEvent(e.probe, mv, "reading", f"{who} now reads a steady {mv} mV.")
        band = f"expected {e.expected_mv} ± {e.tol_mv} mV"
        if fixed:
            return ProbeEvent(e.probe, mv, "fixed",
                              f"{who} is now in the expected range: a steady {mv} mV ({band}). It read {before} mV before.")
        verdict = "in the expected range" if in_band else "outside the expected range"
        return ProbeEvent(e.probe, mv, "reading", f"{who} now reads a steady {mv} mV ({band}: {verdict}).")


class Monitor:
    """Bus consumer: pod samples in, MONITOR events out (the agent turns them into `[event]` turns)."""

    def __init__(self, bench, clock: Callable[[], float] = time.monotonic) -> None:
        self.bench = bench
        self.clock = clock
        self.windows = {p: Window() for p in PROBES}
        self.detectors: dict[str, Detector] = {}
        self.pending: dict[str, tuple[float, ProbeEvent]] = {}  # probe -> (when, event)
        self._gen = bench.session.generation

    async def run(self) -> None:
        q = self.bench.bus.subscribe()
        while True:
            event = await q.get()
            if event.kind == ev.POD_SAMPLE:
                try:
                    self.on_sample(event.data)
                except Exception:
                    log.exception("monitor: bad sample %r", event.data)

    def on_sample(self, sample: dict) -> None:
        now = self.clock()
        s = self.bench.session
        if s.generation != self._gen:  # new student or new lab
            self._gen = s.generation
            self.detectors.clear()
            self.pending.clear()
        mv, lo, hi = sample["mv"], sample.get("lo", sample["mv"]), sample.get("hi", sample["mv"])
        for i, p in enumerate(PROBES):
            self.windows[p].feed(now, mv[i], lo[i], hi[i])
        for p in list(self.detectors):
            if p not in s.expects:
                del self.detectors[p]
                self.pending.pop(p, None)
        for p, e in s.expects.items():
            d = self.detectors.get(p)
            if d is None or d.expect is not e:  # a new request for this probe
                d = self.detectors[p] = Detector(e, self.windows[p].steady())
                self.pending.pop(p, None)
                continue
            found = d.update(mv[PROBES.index(p)], self.windows[p].steady())
            if found:
                log.info("monitor: %s", found.text)
                self.pending[p] = (now, found)
        self.flush(now)

    def flush(self, now: float) -> None:
        for p, (when, e) in list(self.pending.items()):
            if now - when > MAX_AGE_S:
                log.info("monitor: dropped stale event: %s", e.text)
                del self.pending[p]
        if not self.pending or self.bench.session.state is not State.idle:
            return  # never talk over the student, or over Bench
        events = [e for _, e in sorted(self.pending.values(), key=lambda x: x[0])]
        self.pending.clear()
        self.bench.bus.publish(Event(ev.MONITOR, " ".join(e.text for e in events)))
