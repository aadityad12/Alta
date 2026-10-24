"""The agent's tools (CONTRACTS §7): JSON schemas for Claude, and what the server does when they're called.

Every tool validates its input against the current lab and returns (text, is_error). Bad input never
reaches the UI; Claude gets a clear error back instead and can try again.
"""

import json
import logging
import re
import time
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from .protocol import (
    PROBES,
    ExpectOut,
    ManualOut,
    OverlayClearOut,
    OverlayItem,
    OverlayOut,
    SchematicOut,
)

log = logging.getLogger(__name__)

# ---------- breadboard coordinates (CONTRACTS §4) ----------

_ROW = r"([1-9]|[1-5][0-9]|6[0-3])"
HOLE = re.compile(rf"^{_ROW}([a-j])$")
STRIP = re.compile(rf"^{_ROW}:(a-e|f-j)$")
RAIL = re.compile(r"^rail:(a|j)[+-]$")


def place_kind(at: str) -> str | None:
    """'hole', 'strip' or 'rail' for a valid coordinate, else None."""
    if HOLE.match(at):
        return "hole"
    if STRIP.match(at):
        return "strip"
    if RAIL.match(at):
        return "rail"
    return None


def strip_of(hole: str) -> str | None:
    m = HOLE.match(hole)
    if not m:
        return None
    row, col = m.groups()
    return f"{row}:{'a-e' if col <= 'e' else 'f-j'}"


def net_at(lab_data: dict[str, Any], at: str) -> dict[str, Any] | None:
    """The lab net that contains a hole, strip or rail, if any."""
    candidates = {at, strip_of(at)}
    for net in lab_data.get("nets", []):
        if candidates & set(net.get("holes", [])):
            return net
    return None


# ---------- schemas ----------

def _obj(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


_PROBE = {"type": "string", "enum": list(PROBES), "description": "Y = yellow, B = blue, G = green, W = white"}
_PLACE = "Breadboard place: a hole like \"10c\", a strip like \"10:a-e\", or a rail like \"rail:a+\"."
_ITEM = _obj(
    {
        "id": {"type": "string", "description": "Your id for this highlight; reuse it to replace one."},
        "kind": {"type": "string", "enum": ["hole", "strip", "rail", "arrow", "label", "component"]},
        "at": {"type": "string", "description": f"For hole/strip/rail/label. {_PLACE}"},
        "from": {"type": "string", "description": f"For arrow. {_PLACE}"},
        "to": {"type": "string", "description": f"For arrow. {_PLACE}"},
        "text": {"type": "string", "description": "For label: a few words."},
        "ref": {"type": "string", "description": "For component: the part ref from the lab, e.g. \"D1\"."},
        "style": {"type": "string", "enum": ["probe-Y", "probe-B", "probe-G", "probe-W", "attention", "good", "bad"]},
        "pulse": {"type": "boolean"},
    },
    ["id", "kind"],
)

TOOLS: list[dict[str, Any]] = [
    {
        "name": "ask_for_probe",
        "description": (
            "Highlight where the student should put a probe, in that probe's color, and show the expected "
            "reading on screen. It does not speak: say the instruction in your reply. One probe at a time."
        ),
        "input_schema": _obj(
            {
                "probe": _PROBE,
                "at": {"type": "string", "description": f"Where the probe goes. {_PLACE}"},
                "expect_net": {"type": "string", "description": "Net id you expect there (defaults to the net at `at`)."},
            },
            ["probe", "at"],
        ),
    },
    {
        "name": "clear_highlights",
        "description": "Remove every highlight from the student's board view.",
        "input_schema": _obj({}, []),
    },
    {
        "name": "highlight",
        "description": "Highlight holes, strips, rails, parts, arrows or labels on the student's board view.",
        "input_schema": _obj(
            {
                "items": {"type": "array", "items": _ITEM},
                "mode": {"type": "string", "enum": ["replace", "add"], "description": "replace = clear others first"},
            },
            ["items", "mode"],
        ),
    },
    {
        "name": "highlight_schematic",
        "description": "Highlight nets in the schematic on the student's screen. An empty list clears it.",
        "input_schema": _obj({"nets": {"type": "array", "items": {"type": "string"}}}, ["nets"]),
    },
    {
        "name": "look_at_board",
        "description": "Get a camera photo of the breadboard with row numbers drawn on it. Probes beat the camera.",
        "input_schema": _obj({}, []),
    },
    {
        "name": "read_probes",
        "description": (
            "Current reading of each probe: millivolts (average, min and max over the last 50 ms), whether it's "
            "unplugged, where it was last asked to go, and what was expected there."
        ),
        "input_schema": _obj({}, []),
    },
    {
        "name": "record_diagnosis",
        "description": (
            "Log your current diagnosis and the hint level you just used (1 nudge, 2 question, 3 point, 4 fix). "
            "Call it every time you give a hint, and with resolved=true once a fix is confirmed by a measurement."
        ),
        "input_schema": _obj(
            {
                "fault_id": {"type": "string", "description": "A fault id from the lab, or \"unknown\"."},
                "confidence": {"type": "number", "description": "0 to 1"},
                "evidence": {"type": "string", "description": "The measurements behind it, briefly."},
                "hint_level": {"type": "integer", "description": "1 to 4"},
                "resolved": {"type": "boolean"},
            },
            ["fault_id", "confidence", "evidence", "hint_level", "resolved"],
        ),
    },
    {
        "name": "show_manual_step",
        "description": "Scroll the student's manual to a step and highlight it.",
        "input_schema": _obj({"step": {"type": "integer"}}, ["step"]),
    },
]
for _t in TOOLS:
    _t["strict"] = True
TOOL_NAMES = {t["name"] for t in TOOLS}


# ---------- execution ----------

class ToolError(Exception):
    """Bad tool input. The message goes back to Claude as an is_error result."""


class ToolBox:
    def __init__(self, bench, pod_connected: Callable[[], bool] | None = None) -> None:
        self.bench = bench
        self.pod_connected = pod_connected or (lambda: False)

    @property
    def lab(self) -> dict[str, Any]:
        lab = self.bench.lab
        if lab is None:
            raise ToolError("no lab is loaded")
        return lab.data

    async def run(self, name: str, args: Any) -> tuple[str, bool]:
        if name not in TOOL_NAMES:
            return f"unknown tool {name!r}", True
        if not isinstance(args, dict):
            return "tool input must be a JSON object", True
        try:
            result = await getattr(self, f"_{name}")(args)
        except ToolError as e:
            return str(e), True
        except Exception as e:  # a bug in a tool must not kill the turn
            log.exception("tool %s crashed", name)
            return f"internal error in {name}: {e}", True
        return result if isinstance(result, str) else json.dumps(result), False

    # -- tools --

    async def _read_probes(self, args: dict) -> dict:
        s = self.bench.session
        if not s.probes:
            return {"pod_connected": self.pod_connected(), "probes": None,
                    "note": "No readings yet. The pod isn't connected or hasn't sent anything."}
        p = s.probes
        out = {}
        for i, name in enumerate(PROBES):
            mv = p["mv"][i]
            e = s.expects.get(name)
            out[name] = {
                "mv": mv,
                "lo": p.get("lo", p["mv"])[i],
                "hi": p.get("hi", p["mv"])[i],
                "unplugged": mv == -1,
                "asked_at": e.at if e else None,
                "expected_mv": e.expected_mv if e else None,
                "tol_mv": e.tol_mv if e else None,
                "expected_label": e.label if e else None,
            }
        age = round((time.monotonic() - s.probes_at) * 1000) if s.probes_at else None
        return {"pod_connected": self.pod_connected(), "age_ms": age, "vcc_mv": p.get("vcc"), "probes": out}

    async def _ask_for_probe(self, args: dict) -> str:
        probe, at = args.get("probe"), args.get("at", "")
        if probe not in PROBES:
            raise ToolError(f"probe must be one of {', '.join(PROBES)}")
        kind = place_kind(at)
        if kind is None:
            raise ToolError(f"{at!r} isn't a breadboard place. {_PLACE}")
        if args.get("expect_net"):
            net = self._net(args["expect_net"])
        else:
            net = net_at(self.lab, at)
        await self.bench.session.expect(ExpectOut(
            probe=probe, at=at,
            expected_mv=net.get("expected_mv") if net else None,
            tol_mv=net.get("tol_mv") if net else None,
            label=net.get("label") if net else None,
        ))
        await self.bench.hub.broadcast(OverlayOut(mode="add", items=[
            OverlayItem(id=f"probe-{probe}", kind=kind, at=at, style=f"probe-{probe}", pulse=True),
        ]))
        if net:
            return (f"Showing the {probe} probe at {at}, expecting about {net.get('expected_mv')} mV "
                    f"({net.get('label')}). Now tell the student where to put it.")
        return f"Showing the {probe} probe at {at} (no lab net there). Now tell the student where to put it."

    async def _highlight(self, args: dict) -> str:
        items = []
        for raw in args.get("items") or []:
            try:
                item = OverlayItem.model_validate(raw)
            except ValidationError as e:
                raise ToolError(f"bad highlight item {raw}: {e.errors()[0]['msg']}") from None
            self._check_item(item)
            items.append(item)
        if not items:
            raise ToolError("items is empty; use clear_highlights to clear")
        await self.bench.hub.broadcast(OverlayOut(mode=args.get("mode", "replace"), items=items))
        return f"Highlighted {len(items)} item(s)."

    def _check_item(self, item: OverlayItem) -> None:
        if item.kind in ("hole", "strip", "rail"):
            if item.at is None or place_kind(item.at) != item.kind:
                raise ToolError(f"{item.kind} item {item.id!r} needs `at` as a {item.kind}. {_PLACE}")
        elif item.kind == "label":
            if not item.at or not place_kind(item.at) or not item.text:
                raise ToolError(f"label item {item.id!r} needs `at` (a place) and `text`")
        elif item.kind == "arrow":
            if not (item.from_ and item.to and place_kind(item.from_) and place_kind(item.to)):
                raise ToolError(f"arrow item {item.id!r} needs `from` and `to` places. {_PLACE}")
        elif item.kind == "component":
            refs = [p.get("ref") for p in self.lab.get("parts", [])]
            if item.ref not in refs:
                raise ToolError(f"component item {item.id!r}: ref must be one of {', '.join(refs)}")

    async def _clear_highlights(self, args: dict) -> str:
        await self.bench.hub.broadcast(OverlayClearOut())
        return "Cleared all highlights."

    async def _show_manual_step(self, args: dict) -> str:
        step = args.get("step")
        steps = [s.get("n") for s in self.lab.get("steps", [])]
        if step not in steps:
            raise ToolError(f"step must be one of {steps}")
        self.bench.session.step = step
        await self.bench.hub.broadcast(ManualOut(step=step))
        return f"Showing manual step {step}."

    async def _highlight_schematic(self, args: dict) -> str:
        nets = args.get("nets") or []
        for n in nets:
            self._net(n)
        await self.bench.hub.broadcast(SchematicOut(nets=nets))
        return f"Highlighted nets: {', '.join(nets)}." if nets else "Cleared the schematic highlight."

    async def _look_at_board(self, args: dict) -> str:
        raise ToolError("The camera isn't connected yet. Rely on the probes, or ask the student what they see.")

    async def _record_diagnosis(self, args: dict) -> str:
        fault_id = args.get("fault_id")
        faults = [f.get("id") for f in self.lab.get("faults", [])]
        if fault_id != "unknown" and fault_id not in faults:
            raise ToolError(f"fault_id must be \"unknown\" or one of {', '.join(faults)}")
        level, conf = args.get("hint_level"), args.get("confidence")
        if not isinstance(level, int) or not 1 <= level <= 4:
            raise ToolError("hint_level must be 1, 2, 3 or 4")
        if not isinstance(conf, (int, float)) or not 0 <= conf <= 1:
            raise ToolError("confidence must be between 0 and 1")
        s = self.bench.session
        entry = {"t": time.time(), "lab": s.lab_id, "fault_id": fault_id, "confidence": conf,
                 "evidence": args.get("evidence", ""), "hint_level": level, "resolved": bool(args.get("resolved"))}
        s.diagnoses.append(entry)
        s.hint_levels[fault_id] = max(s.hint_levels.get(fault_id, 0), level)
        log.info("diagnosis: %s", entry)
        return "Recorded."

    def _net(self, net_id: str) -> dict[str, Any]:
        for net in self.lab.get("nets", []):
            if net.get("id") == net_id:
                return net
        ids = [n.get("id") for n in self.lab.get("nets", [])]
        raise ToolError(f"unknown net {net_id!r}; nets are {', '.join(ids)}")
