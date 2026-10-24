"""WebSocket hub and the server core that ties clients, session, labs and the event bus together."""

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

from . import bus as ev
from .bus import Event, EventBus
from .labs import Lab
from .protocol import (
    PROBES,
    ErrorOut,
    ExpectOut,
    LabOut,
    ManualOut,
    OverlayClearOut,
    ProbesOut,
    ResetIn,
    SelectLabIn,
    State,
    StateOut,
    StepIn,
    _Msg,
)
from .session import Session

log = logging.getLogger(__name__)

PROBES_HZ = 10


class Hub:
    """Connected browser clients."""

    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()

    async def send(self, ws: WebSocket, msg: _Msg) -> None:
        try:
            await ws.send_json(msg.wire())
        except Exception:
            self.clients.discard(ws)

    async def broadcast(self, msg: _Msg) -> None:
        if self.clients:
            data = msg.wire()
            await asyncio.gather(*(self._send_raw(ws, data) for ws in list(self.clients)))

    async def _send_raw(self, ws: WebSocket, data: dict[str, Any]) -> None:
        try:
            await ws.send_json(data)
        except Exception:
            self.clients.discard(ws)


class Bench:
    """Server core. The pod bridge (#16), agent (#17) and voice (#18/#19) plug in via `bus` and `session`."""

    def __init__(self, labs: dict[str, Lab]) -> None:
        self.labs = labs
        self.hub = Hub()
        self.bus = EventBus()
        self.session = Session(broadcast=self.hub.broadcast)
        self.session.lab_id = next(iter(sorted(labs)), None)
        self._probes_dirty = False

    @property
    def lab(self) -> Lab | None:
        return self.labs.get(self.session.lab_id) if self.session.lab_id else None

    # ---------- clients ----------

    async def connect(self, ws: WebSocket) -> None:
        """Bring a new client up to date: lab, state, step, latest probes, pending expects."""
        self.hub.clients.add(ws)
        s = self.session
        if self.lab:
            await self.hub.send(ws, LabOut(lab=self.lab.wire()))
        else:
            await self.hub.send(ws, ErrorOut(message="no labs found in labs/"))
        await self.hub.send(ws, StateOut(value=s.state, detail=s.detail))
        await self.hub.send(ws, ManualOut(step=s.step))
        if s.probes:
            await self.hub.send(ws, self._probes_msg())
        for e in s.expects.values():
            await self.hub.send(ws, e)

    def disconnect(self, ws: WebSocket) -> None:
        self.hub.clients.discard(ws)

    # ---------- event handling ----------

    async def run(self) -> None:
        """Consume bus events and push throttled probe readings. Runs for the app's lifetime."""
        await asyncio.gather(self._consume(), self._probe_ticker())

    async def _consume(self) -> None:
        q = self.bus.subscribe()
        while True:
            event = await q.get()
            try:
                await self.handle(event)
            except Exception:
                log.exception("error handling %s", event)

    async def handle(self, event: Event) -> None:
        if event.kind == ev.POD_SAMPLE:
            self.session.probes = event.data
            self._probes_dirty = True
        elif event.kind == ev.UI:
            await self._handle_ui(event.data, event.client)

    async def _handle_ui(self, msg: _Msg, client: WebSocket | None) -> None:
        if isinstance(msg, SelectLabIn):
            if msg.lab_id not in self.labs:
                if client:
                    await self.hub.send(client, ErrorOut(message=f"unknown lab: {msg.lab_id}"))
                return
            await self.select_lab(msg.lab_id)
        elif isinstance(msg, StepIn):
            self.session.step = msg.step
        elif isinstance(msg, ResetIn):
            await self.reset()
        # hello / ptt / text / frame are for the voice + agent consumers (#17, #18, #20)

    async def select_lab(self, lab_id: str) -> None:
        self.session.lab_id = lab_id
        await self._fresh_start()

    async def reset(self) -> None:
        """New student: clear the session, keep the lab, and tell every client to start over."""
        await self._fresh_start()

    async def _fresh_start(self) -> None:
        s = self.session
        pending = list(s.expects)
        s.clear()
        if self.lab:
            await self.hub.broadcast(LabOut(lab=self.lab.wire()))
        await self.hub.broadcast(OverlayClearOut())
        for probe in pending:
            await self.hub.broadcast(ExpectOut(probe=probe, clear=True))
        await self.hub.broadcast(ManualOut(step=s.step))
        if s.state is State.idle:
            await s.broadcast(StateOut(value=State.idle))  # still re-announce, so the UI resets too
        else:
            await s.set_state(State.idle)

    # ---------- probes ----------

    def _probes_msg(self) -> ProbesOut:
        p = self.session.probes or {}
        n = len(PROBES)
        return ProbesOut(
            mv=p.get("mv", [-1] * n),
            lo=p.get("lo", p.get("mv", [-1] * n)),
            hi=p.get("hi", p.get("mv", [-1] * n)),
            vcc=p.get("vcc", 0),
            btn=p.get("btn", 0),
            t=p.get("t", 0),
        )

    async def _probe_ticker(self) -> None:
        """The pod sends 20 Hz; the UI gets the latest reading at most PROBES_HZ times a second."""
        while True:
            await asyncio.sleep(1 / PROBES_HZ)
            if self._probes_dirty:
                self._probes_dirty = False
                await self.hub.broadcast(self._probes_msg())
