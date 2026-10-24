"""WebSocket message models. Mirrors docs/CONTRACTS.md §5 (source of truth: issue #2)."""

from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

Probe = Literal["Y", "B", "G", "W"]
PROBES: tuple[Probe, ...] = ("Y", "B", "G", "W")


class State(str, Enum):
    idle = "idle"
    listening = "listening"
    transcribing = "transcribing"
    thinking = "thinking"
    speaking = "speaking"
    error = "error"


class _Msg(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    def wire(self) -> dict[str, Any]:
        """JSON-ready dict: contract field names, optional fields left out when unset."""
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)


# ---------- server -> web ----------

class LabOut(_Msg):
    type: Literal["lab"] = "lab"
    lab: dict[str, Any]


class ProbesOut(_Msg):
    type: Literal["probes"] = "probes"
    mv: list[int]
    lo: list[int]
    hi: list[int]
    vcc: int
    btn: int
    t: int


class ExpectOut(_Msg):
    type: Literal["expect"] = "expect"
    probe: Probe
    at: str | None = None
    expected_mv: int | None = None
    tol_mv: int | None = None
    label: str | None = None
    clear: bool | None = None


class OverlayItem(_Msg):
    id: str
    kind: Literal["hole", "strip", "rail", "arrow", "label", "component"]
    at: str | None = None
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None
    text: str | None = None
    ref: str | None = None
    style: Literal["probe-Y", "probe-B", "probe-G", "probe-W", "attention", "good", "bad"] | None = None
    pulse: bool | None = None


class OverlayOut(_Msg):
    type: Literal["overlay"] = "overlay"
    mode: Literal["replace", "add"] = "replace"
    items: list[OverlayItem]


class OverlayClearOut(_Msg):
    type: Literal["overlay_clear"] = "overlay_clear"


class ManualOut(_Msg):
    type: Literal["manual"] = "manual"
    step: int


class SchematicOut(_Msg):
    type: Literal["schematic"] = "schematic"
    nets: list[str]


class TranscriptOut(_Msg):
    type: Literal["transcript"] = "transcript"
    role: Literal["student", "bench", "system"]
    text: str
    final: bool = True


class StateOut(_Msg):
    type: Literal["state"] = "state"
    value: State
    detail: str | None = None


class RequestFrameOut(_Msg):
    type: Literal["request_frame"] = "request_frame"
    id: str


class ErrorOut(_Msg):
    type: Literal["error"] = "error"
    message: str


# ---------- web -> server ----------

class HelloIn(_Msg):
    type: Literal["hello"]
    client: str


class SelectLabIn(_Msg):
    type: Literal["select_lab"]
    lab_id: str


class PttIn(_Msg):
    type: Literal["ptt"]
    down: bool


class TextIn(_Msg):
    type: Literal["text"]
    text: str


class FrameIn(_Msg):
    type: Literal["frame"]
    id: str
    jpeg_b64: str
    w: int
    h: int


class StepIn(_Msg):
    type: Literal["step"]
    step: int


class ResetIn(_Msg):
    type: Literal["reset"]


Inbound = Annotated[
    Union[HelloIn, SelectLabIn, PttIn, TextIn, FrameIn, StepIn, ResetIn],
    Field(discriminator="type"),
]
_inbound = TypeAdapter(Inbound)


class BadMessage(ValueError):
    """Raised for inbound messages we can't accept; str() is safe to send back to the client."""


def parse_inbound(raw: Any) -> Inbound:
    if not isinstance(raw, dict):
        raise BadMessage("expected a JSON object")
    try:
        return _inbound.validate_python(raw)
    except ValidationError as e:
        err = e.errors()[0]
        if err["type"] in ("union_tag_invalid", "union_tag_not_found"):
            raise BadMessage(f"unknown message type: {raw.get('type')!r}") from None
        where = ".".join(str(p) for p in err["loc"][1:]) or "message"
        raise BadMessage(f"bad {raw.get('type')!r} message: {where}: {err['msg']}") from None
