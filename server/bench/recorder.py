"""Session log (#23) and per-turn latency marks (#22).

One JSONL file per student, recordings/<start time>-<lab>.jsonl, started fresh on every reset / new lab.
Each line is {"t": seconds since the session started, "kind": ..., ...}. Kinds:

    session {lab, wall}           ptt {down}                    state {value, detail}
    transcript {role, text}       expect {probe, at, ...}       pod {connected}
    stt {ms, clip_s, text}        turn {source, text}           first_text {}
    claude {ms, ttft_ms, ...}     tool {name, input, error}     turn_end {reply, silent}
    first_sentence {}             first_audio {ms}              monitor {text}

BENCH_RECORD_DIR picks the folder ("off" = no log). The file only appears once something happens.
At the end of every spoken turn the latency from button release is logged (see metrics.turn_timing).
"""

import json
import logging
import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from .metrics import format_timing, turn_timing

log = logging.getLogger(__name__)

RECORD_DIR = Path(__file__).resolve().parents[2] / "recordings"


class Recorder:
    def __init__(self, directory: Path, clock: Callable[[], float] = time.monotonic) -> None:
        self.dir = directory
        self.clock = clock
        self.path: Path | None = None
        self._file: TextIO | None = None
        self._t0 = clock()
        self._lab: str | None = None
        self._turn: list[dict] | None = None  # records since the last talk-button release

    @classmethod
    def from_env(cls) -> "Recorder | None":
        value = os.environ.get("BENCH_RECORD_DIR", "").strip()
        if value.lower() in ("off", "none", "0"):
            return None
        return cls(Path(value) if value else RECORD_DIR)

    def start(self, lab_id: str | None) -> None:
        """A new student session. The file is opened lazily, on the first record."""
        self.close()
        self._t0, self._lab, self._turn = self.clock(), lab_id, None

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    def __call__(self, kind: str, **fields: Any) -> None:
        rec = {"t": round(self.clock() - self._t0, 3), "kind": kind, **fields}
        try:
            self._write(rec)
        except OSError as e:
            log.warning("session log: %r (logging off)", e)
            self.dir = None  # don't spam
        self._track(rec)

    def _write(self, rec: dict) -> None:
        if self.dir is None:
            return
        if self._file is None:
            self.dir.mkdir(parents=True, exist_ok=True)
            name = time.strftime("%Y%m%d-%H%M%S") + "-" + re.sub(r"[^\w.-]", "_", self._lab or "nolab")
            self.path, n = self.dir / f"{name}.jsonl", 2
            while self.path.exists():  # two students in the same second (quick resets)
                self.path, n = self.dir / f"{name}-{n}.jsonl", n + 1
            self._file = self.path.open("a", buffering=1, encoding="utf-8")  # line-buffered: a crash loses nothing
            self._file.write(json.dumps({"t": 0.0, "kind": "session", "lab": self._lab, "wall": time.time()}) + "\n")
        self._file.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    def _track(self, rec: dict) -> None:
        """Collect one spoken turn (release -> ... -> back to idle) and log its timing."""
        kind = rec["kind"]
        if kind == "ptt":
            self._turn = [rec] if not rec.get("down") else None
            return
        if self._turn is None:
            return
        self._turn.append(rec)
        if kind == "state" and rec.get("value") in ("idle", "listening", "error"):
            timing = turn_timing(self._turn)
            self._turn = None
            if timing and "stt" in timing:
                log.info("latency: %s", format_timing(timing))
