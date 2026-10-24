"""Brain view: a dev page at /brain that shows what Bench is doing and what Claude is given.

    POD_PORT=mock uv run python -m bench          # then open http://localhost:8000/brain

It's a student-screen stand-in until the real one exists (#28-#30), not a replacement for it:
- talks to /ws with exactly the CONTRACTS §5 messages the student screen will use (ptt, text, reset,
  select_lab, frame), and draws lab, state, transcript, expect, overlay and probes from it
- /brain/ws is a separate dev feed of the agent's inputs: what the student said, probe events, every
  tool call with the result Claude got back, timings. Not part of the contract.
- POD_PORT=mock runs the mock pod's voltage model (#9) inside the server, so you can stage a fault, fix
  it and plug probes from the page (click a hole). With a real pod those controls are hidden.
- it can answer Bench's camera requests with a sample photo (docs/samples, #34), so look_at_board works
  before the real camera + overlay engine (#11) exist. Off by default: the photo isn't the staged board.
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from . import bus as ev
from .bus import Event
from .protocol import PROBES

log = logging.getLogger(__name__)

PAGE = Path(__file__).resolve().parent / "static" / "brain.html"
SAMPLES = Path(__file__).resolve().parents[2] / "docs" / "samples"
FEED_KINDS = {"turn", "tool", "claude", "turn_end", "monitor", "stt", "first_audio", "filler", "ptt"}


class MockBoard:
    """The mock pod's model (#9) in-process: a 50 ms sample on the bus, like the real pod's serial lines."""

    def __init__(self, bench, labs_dir: Path) -> None:
        from .scenarios import mock_pod  # loads tools/mock_pod.py

        self.mock = mock_pod
        self.bench = bench
        self.pod = mock_pod.MockPod(labs_dir, None, None)
        os.close(self.pod.master)
        os.close(self.pod.slave)
        self.lab_id: str | None = None
        self.fault: str | None = None

    def _sync_lab(self) -> None:
        lab_id = self.bench.session.lab_id
        if lab_id and lab_id != self.lab_id:
            faults = [f["id"] for f in self.bench.labs[lab_id].data.get("faults", [])]
            self.lab_id, self.fault = lab_id, (faults[0] if faults else None)
            self.pod.load_lab(lab_id, self.fault or "normal")
            self.pod.command("unplug all")

    async def run(self) -> None:
        self.bench.bus.publish(Event(ev.POD_STATUS, True))
        while True:
            self._sync_lab()
            r = [self.pod.reading(p, self.mock.VCC_MV) for p in PROBES]
            self.bench.bus.publish(Event(ev.POD_SAMPLE, {"mv": [x[0] for x in r], "lo": [x[1] for x in r],
                                                         "hi": [x[2] for x in r], "vcc": self.mock.VCC_MV,
                                                         "btn": 0, "t": 0}))
            await asyncio.sleep(self.mock.TICK_S)

    def command(self, cmd: str) -> None:
        self._sync_lab()
        word = cmd.split()[0].lower()
        if word == "fault":
            self.pod.command(cmd)
            self.fault = cmd.split()[1]
        elif word == "fix":
            self.pod.command("fix")
            self.fault = None
        else:
            self.pod.command(cmd)

    def status(self) -> dict[str, Any]:
        self._sync_lab()
        lab = self.bench.labs.get(self.lab_id)
        return {"available": True, "lab": self.lab_id, "fault": self.fault, "light": self.pod.light,
                "faults": [{"id": f["id"], "name": f["name"]} for f in (lab.data.get("faults", []) if lab else [])],
                "probes": dict(self.pod.probes)}


class BrainFeed:
    """Fans the agent's inputs out to every open /brain/ws."""

    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()

    def emit(self, item: dict[str, Any]) -> None:
        if not self.clients:
            return
        data = json.dumps(item, ensure_ascii=False, default=str)
        for ws in list(self.clients):
            asyncio.ensure_future(self._send(ws, data))

    async def _send(self, ws: WebSocket, data: str) -> None:
        try:
            await ws.send_text(data)
        except Exception:
            self.clients.discard(ws)


class BoardCmd(BaseModel):
    cmd: str


def mount(app: FastAPI, bench, agent, board: MockBoard | None) -> BrainFeed:
    feed = BrainFeed()
    record = bench.session.record

    def recorded(kind: str, **fields: Any) -> None:
        record(kind, **fields)
        if kind in FEED_KINDS and kind != "tool":  # tool calls come with their results via on_tool_call
            feed.emit({"kind": kind, **fields})

    bench.session.record = recorded
    if agent is not None:
        previous = agent.on_tool_call

        def on_tool(name, inp, result, is_error):
            if previous:
                previous(name, inp, result, is_error)
            shown = result if isinstance(result, str) else "(a camera photo)"
            feed.emit({"kind": "tool", "name": name, "input": inp, "result": shown[:2000], "error": is_error})

        agent.on_tool_call = on_tool

    @app.get("/brain")
    def page() -> FileResponse:
        return FileResponse(PAGE)

    @app.websocket("/brain/ws")
    async def brain_ws(ws: WebSocket) -> None:
        await ws.accept()
        feed.clients.add(ws)
        await ws.send_text(json.dumps({"kind": "hello", "model": agent.model if agent else None,
                                       "fast": bool(agent and agent.speed == "fast")}))
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            feed.clients.discard(ws)

    @app.get("/brain/system", response_class=PlainTextResponse)
    def system_prompt() -> str:
        return agent.system_prompt() if agent else "(no agent: demo UI mode)"

    @app.get("/brain/board")
    def board_status() -> dict:
        return board.status() if board else {"available": False}

    @app.post("/brain/board")
    def board_command(body: BoardCmd) -> dict:
        if board is None:
            raise HTTPException(404, "no mock board: start the server with POD_PORT=mock")
        try:
            board.command(body.cmd.strip())
        except (ValueError, IndexError, KeyError) as e:
            raise HTTPException(400, f"bad command {body.cmd!r}: {e}") from None
        return board.status()

    @app.get("/brain/samples")
    def samples() -> list[str]:
        return sorted(p.name for p in SAMPLES.glob("*.jpg")) if SAMPLES.is_dir() else []

    @app.get("/brain/samples/{name}")
    def sample(name: str) -> FileResponse:
        f = (SAMPLES / name).resolve()
        if not f.is_relative_to(SAMPLES.resolve()) or not f.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(f)

    return feed
