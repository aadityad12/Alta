"""Async event bus. Every subscriber gets its own queue, so each consumer sees every event.

Producers: pod bridge, PTT, UI messages, monitor. Consumers: agent, broadcaster.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

# Event kinds
POD_SAMPLE = "pod_sample"  # data: the pod's sample line (dict, CONTRACTS §2)
POD_EVENT = "pod_event"    # data: the pod's event line, e.g. {"evt":"btn","down":1,"t":...}
UI = "ui"                  # data: a parsed web->server message (protocol.*In)
MONITOR = "monitor"        # data: probe-change event (#21)


@dataclass
class Event:
    kind: str
    data: Any = None
    client: Any = field(default=None, repr=False)  # the WebSocket a UI event came from


class EventBus:
    def __init__(self, maxsize: int = 1000) -> None:
        self._subs: list[asyncio.Queue[Event]] = []
        self._maxsize = maxsize

    def subscribe(self) -> asyncio.Queue[Event]:
        q: asyncio.Queue[Event] = asyncio.Queue(self._maxsize)
        self._subs.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[Event]) -> None:
        if q in self._subs:
            self._subs.remove(q)

    def publish(self, event: Event) -> None:
        for q in self._subs:
            if q.full():
                # A stuck consumer must not stall the pod or the UI: drop its oldest event.
                q.get_nowait()
                log.warning("bus: consumer queue full, dropped oldest event")
            q.put_nowait(event)
