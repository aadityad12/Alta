"""What's broken right now, for the student screen's banners (#31).

Three parts, each "ok", "down" or "off" (not set up, e.g. POD_PORT=off or no API key):
- pod:   the probe pod's USB link (#16)
- ai:    Claude (#17): a turn or the cache pre-warm failed with a network / API error
- voice: Cartesia speech-to-text (#18) or text-to-speech (#19)

A part goes down on a failure and back to ok on its next success, so the banner stays up exactly as long
as the problem does. It's separate from the conversation `state`: the student can keep talking or typing
while a banner is up. Changes are broadcast as `health` (CONTRACTS §5) and logged to the session log.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Literal

from .protocol import HealthOut

log = logging.getLogger(__name__)

Part = Literal["pod", "ai", "voice"]
Status = Literal["ok", "down", "off"]

# The one line the screen shows while a part is down: what to do about it.
FIX: dict[str, str] = {
    "pod": "Plug the pod's USB cable back in",
    "ai": "ALTA can't reach its brain. Check internet / hotspot",
    "voice": "ALTA's voice service isn't responding. Check internet / hotspot (press / to type)",
}


class Health:
    def __init__(self, broadcast: Callable[[HealthOut], Awaitable[None]],
                 record: Callable[..., None] = lambda kind, **f: None) -> None:
        self._broadcast = broadcast
        self.record = record
        self.status: dict[str, Status] = {"pod": "ok", "ai": "ok", "voice": "ok"}

    def msg(self) -> HealthOut:
        return HealthOut(**self.status, fix={p: FIX[p] for p, v in self.status.items() if v == "down"})

    def off(self, part: Part) -> None:
        """At startup: this part isn't set up, so it never shows a banner."""
        self.status[part] = "off"

    def waiting(self, part: Part) -> None:
        """At startup: down until it first works (the pod hasn't said hello yet)."""
        self.status[part] = "down"

    async def ok(self, part: Part) -> None:
        await self._set(part, "ok")

    async def down(self, part: Part, why: str = "") -> None:
        await self._set(part, "down", why)

    async def _set(self, part: Part, status: Status, why: str = "") -> None:
        if self.status[part] in (status, "off"):
            return
        self.status[part] = status
        (log.warning if status == "down" else log.info)("health: %s %s%s", part, status, f" ({why})" if why else "")
        self.record("health", part=part, status=status, why=why or None)
        await self._broadcast(self.msg())
