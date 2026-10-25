"""TA dashboard (#24): one TA watching a room of lab stations, at /ta.

Station 1 is this server's live session. Stations 2-6 replay real scenario sessions (#23, bench/ta_samples,
made by tools/make_ta_samples.py) slowed down REPLAY_SCALE times, on a loop: build for a while, get stuck,
get helped, fix it, start the next lab.

Both come from the same records the session log writes (recorder.py), read by StationView. The live one
tees `session.record`, so it works with logging on or off. Only status is shown: lab, step, how long a
student has been stuck, ALTA's latest diagnosis and hint level, and what's broken. Never words, audio or
video (privacy).
"""

import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse

SAMPLES = Path(__file__).parent / "ta_samples"
PAGE = Path(__file__).parent / "static" / "ta.html"
REPLAY_SCALE = 15    # a replayed session's seconds x this: 8-14 simulated s -> 2-3.5 min stuck
BUILD_S = (150, 330)  # replayed stations build for this long before they get stuck (varies per station)
# How often each fault comes up in the replayed room, so the chart has a shape (the rest: once per round)
FAULT_WEIGHT = {"led_reversed": 3, "missing_ground_wire": 2, "wrong_resistor_10k": 2}
FIXED_S = 25         # how long "fixed" shows before the next lab starts
CALM_AFTER_S = 60    # the live station goes from "fixed" back to "building" after this
WARM_START_S = 1500  # the replayed room starts 25 min into the session, so the fault chart has history


class StationView:
    """The status of one station, built from its session records in order."""

    def __init__(self, lab: str | None) -> None:
        self.lab = lab
        self.step = 1
        self.state = "idle"
        self.stuck_since: float | None = None
        self.fixed_at: float | None = None
        self.fault: str | None = None
        self.hint = 0
        self.confidence = 0.0
        self.down: list[str] = []
        self.fixed = Counter()  # fault_id -> times fixed at this station

    def feed(self, t: float, rec: dict[str, Any]) -> None:
        kind = rec.get("kind")
        if kind == "turn" and rec.get("source") == "student" and self.stuck_since is None:
            self.stuck_since, self.fixed_at = t, None
            self.fault, self.hint, self.confidence = None, 0, 0.0
        elif kind == "state":
            self.state = rec.get("value") or self.state
        elif kind == "health":
            part = rec.get("part")
            self.down = [p for p in self.down if p != part] + ([part] if rec.get("status") == "down" else [])
        elif kind == "tool" and not rec.get("error"):
            args = rec.get("input") or {}
            if rec.get("name") == "show_manual_step" and isinstance(args.get("step"), int):
                self.step = args["step"]
            elif rec.get("name") == "record_diagnosis":
                fault = args.get("fault_id")
                if fault and fault != "unknown":
                    self.fault = fault
                self.hint = max(self.hint, int(args.get("hint_level") or 0))
                self.confidence = float(args.get("confidence") or 0)
                if args.get("resolved"):
                    if self.fault:
                        self.fixed[self.fault] += 1
                    self.stuck_since, self.fixed_at = None, t

    def status(self, now: float) -> str:
        if self.stuck_since is not None:
            return "stuck"
        if self.fixed_at is not None and now - self.fixed_at < CALM_AFTER_S:
            return "fixed"
        return "building"

    def card(self, now: float, labs: dict, name: str, live: bool) -> dict[str, Any]:
        lab = labs.get(self.lab)
        data = lab.data if lab else {}
        faults = {f["id"]: f.get("name", f["id"]) for f in data.get("faults", [])}
        return {
            "name": name, "live": live, "lab": self.lab, "lab_title": data.get("title", self.lab or "no lab"),
            "step": self.step, "steps": len(data.get("steps", [])) or None, "state": self.state,
            "status": self.status(now),
            "stuck_s": round(now - self.stuck_since) if self.stuck_since is not None else None,
            "fault": self.fault, "fault_name": faults.get(self.fault, self.fault) if self.fault else None,
            "hint": self.hint, "confidence": round(self.confidence, 2), "down": self.down,
        }


class ReplayStation:
    """A simulated station: replays sample sessions on a loop. Its view is a pure function of the time."""

    def __init__(self, name: str, sessions: list[list[dict]], offset: float, build_s: float) -> None:
        self.name, self.sessions, self.offset, self.build_s = name, sessions, offset, build_s

    def view_at(self, elapsed: float) -> StationView:
        t, i, fixed = elapsed + self.offset, 0, Counter()
        while True:
            recs = self.sessions[i % len(self.sessions)]
            replay = recs[-1]["t"] * REPLAY_SCALE
            if t < self.build_s + replay + FIXED_S:
                break
            t -= self.build_s + replay + FIXED_S
            fixed[recs[0].get("fault")] += 1
            i += 1
        view = StationView(recs[0].get("lab"))
        view.fixed = fixed
        if t < self.build_s:  # building: walk through the manual's steps
            view.step = 1 + int(t / self.build_s * 3)
            return view
        view.step = 3
        for rec in recs[1:]:
            if rec["t"] * REPLAY_SCALE > t - self.build_s:
                break
            view.feed(rec["t"] * REPLAY_SCALE, rec)
        view.stuck_since = None if view.stuck_since is None else view.stuck_since - (t - self.build_s)
        view.fixed_at = None if view.fixed_at is None else view.fixed_at - (t - self.build_s)
        return view  # stuck_since / fixed_at are now relative to "now" = 0


def load_samples(folder: Path = SAMPLES) -> list[list[dict]]:
    return [[json.loads(line) for line in p.open(encoding="utf-8")] for p in sorted(folder.glob("*.jsonl"))]


class Room:
    def __init__(self, bench, samples: list[list[dict]] | None = None, n_replay: int = 5,
                 clock=time.monotonic) -> None:
        self.bench, self.clock = bench, clock
        self.t0 = clock() - WARM_START_S
        s = bench.session
        self._gen = s.generation
        self.live = StationView(s.lab_id)
        before = s.record

        def tee(kind: str, **fields: Any) -> None:
            before(kind, **fields)
            self._feed_live(kind, fields)

        s.record = tee
        samples = load_samples() if samples is None else samples
        playlist = [r for r in samples for _ in range(FAULT_WEIGHT.get(r[0].get("fault"), 1))]
        playlist = playlist[::3] + playlist[1::3] + playlist[2::3]  # spread the repeats out
        self.replays = [
            ReplayStation(f"Station {k + 2}", playlist[k * 3:] + playlist[:k * 3], offset=k * 97.0,
                          build_s=BUILD_S[0] + (k * 37) % (BUILD_S[1] - BUILD_S[0]))
            for k in range(n_replay if samples else 0)
        ]

    def _feed_live(self, kind: str, fields: dict) -> None:
        self._check_reset()
        self.live.feed(self.clock(), {"kind": kind, **fields})

    def _check_reset(self) -> None:
        s = self.bench.session
        if s.generation != self._gen or s.lab_id != self.live.lab:  # new student or new lab
            self._gen, self.live = s.generation, StationView(s.lab_id)

    def snapshot(self) -> dict[str, Any]:
        now, labs, s = self.clock(), self.bench.labs, self.bench.session
        self._check_reset()
        self.live.step, self.live.state = s.step, s.state.value
        health = getattr(s, "health", None)  # #31's health tracker, when it's there
        self.live.down = [p for p, v in health.status.items() if v == "down"] if health else []
        cards = [self.live.card(now, labs, "Station 1", live=True)]
        counts = Counter(self.live.fixed)
        for r in self.replays:
            view = r.view_at(now - self.t0)
            cards.append(view.card(0.0, labs, r.name, live=False))
            counts.update(view.fixed)
        for c in cards:  # a fault diagnosed right now counts too
            if c["status"] == "stuck" and c["fault"]:
                counts[c["fault"]] += 1
        names = {f["id"]: (f.get("name", f["id"]), lab.data.get("title", lab.id))
                 for lab in labs.values() for f in lab.data.get("faults", [])}
        faults = [{"id": f, "name": names.get(f, (f, ""))[0], "lab": names.get(f, ("", ""))[1], "count": n}
                  for f, n in counts.most_common() if f]
        return {"stations": cards, "faults": faults}


def mount(app: FastAPI, room: Room) -> None:
    @app.get("/ta")
    def ta_page() -> FileResponse:
        return FileResponse(PAGE)

    @app.get("/ta/stations")
    def ta_stations() -> dict:
        return room.snapshot()
