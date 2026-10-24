"""Per-student session: current lab, step, probes, pending expects, hints, transcript, and the state machine."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from .protocol import ExpectOut, State, StateOut, TranscriptOut, _Msg

log = logging.getLogger(__name__)

Broadcast = Callable[[_Msg], Awaitable[None]]
PodCommand = Callable[[str], Awaitable[None]]

LED_FOR_STATE = {
    State.idle: "IDLE",
    State.listening: "LISTEN",
    State.transcribing: "THINK",
    State.thinking: "THINK",
    State.speaking: "SPEAK",
    State.error: "ERROR",
}

# idle -> listening -> transcribing -> thinking -> speaking -> idle, plus:
#   idle -> thinking (typed text, probe events), speaking -> listening (barge-in),
#   transcribing -> speaking ("I didn't catch that").
# Any state may go to idle or error.
_NEXT = {
    State.idle: {State.listening, State.thinking},
    State.listening: {State.transcribing},
    State.transcribing: {State.thinking, State.speaking},
    State.thinking: {State.speaking},
    State.speaking: {State.listening},
    State.error: set(),
}


def can_transition(old: State, new: State) -> bool:
    return new in (State.idle, State.error) or new in _NEXT[old]


async def _no_pod(cmd: str) -> None:
    log.debug("no pod connected, dropping %r", cmd)


def _no_record(kind: str, **fields: Any) -> None:
    pass


@dataclass
class Session:
    broadcast: Broadcast
    pod_command: PodCommand = _no_pod
    record: Callable[..., None] = _no_record  # the session log (recorder.Recorder, #23)

    lab_id: str | None = None
    step: int = 1
    probes: dict[str, Any] | None = None  # latest pod sample line
    probes_at: float | None = None  # time.monotonic() when it arrived
    expects: dict[str, ExpectOut] = field(default_factory=dict)  # probe -> pending request
    hint_levels: dict[str, int] = field(default_factory=dict)  # fault_id -> highest hint level given
    transcript: list[TranscriptOut] = field(default_factory=list)
    diagnoses: list[dict[str, Any]] = field(default_factory=list)  # record_diagnosis log (metrics, #23/#24)
    state: State = State.idle
    detail: str | None = None
    generation: int = 0  # bumped on every reset, so long-running tasks can notice

    async def set_state(self, new: State, detail: str | None = None) -> bool:
        """Move the state machine. Broadcasts `state` and sets the pod LED. Returns False if refused."""
        if not can_transition(self.state, new):
            log.warning("refused state change %s -> %s", self.state.value, new.value)
            return False
        self.state, self.detail = new, detail
        self.record("state", value=new.value, detail=detail)
        await self.broadcast(StateOut(value=new, detail=detail))
        await self.pod_command(f"LED {LED_FOR_STATE[new]}")
        return True

    async def say(self, role: str, text: str, final: bool = True) -> None:
        msg = TranscriptOut(role=role, text=text, final=final)
        if final:
            self.transcript.append(msg)
            self.record("transcript", role=role, text=text)
        await self.broadcast(msg)

    async def expect(self, msg: ExpectOut) -> None:
        self.record("expect", **msg.wire())
        if msg.clear:
            self.expects.pop(msg.probe, None)
        else:
            self.expects[msg.probe] = msg
        await self.broadcast(msg)

    def clear(self) -> None:
        """Forget the student: everything except which lab is loaded."""
        self.step = 1
        self.expects.clear()
        self.hint_levels.clear()
        self.transcript.clear()
        self.diagnoses.clear()
        self.generation += 1
