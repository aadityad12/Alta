"""Claude agent loop + tools (#17).

One turn = one student utterance (or one probe event): stream a reply from Claude, run the tools it
asks for (at most MAX_ROUNDS rounds), and speak its final text. The conversation history is kept for
the whole session and cleared on reset / select_lab.

API notes (checked against the Claude docs, not guessed):
- adaptive thinking is always on for claude-opus-5-5; effort is the only knob, and we keep it low for speed
- server-side refusal fallback: beta `server-side-fallback-2026-07-01` + `fallbacks="default"`
- always look at stop_reason before using the content
- the system prompt is frozen per lab and cached; history is cached with top-level automatic caching
- assistant turns are appended exactly as returned (thinking blocks included) and never edited
"""

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import anthropic

from . import bus as ev
from .protocol import State, TextIn
from .tools import TOOLS, ToolBox

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_ROUNDS = 6
TURN_TIMEOUT_S = 20.0
MAX_TOKENS = 16000  # thinking counts against this too; replies themselves are a sentence or two
SILENT = "<silent>"
GLITCH_LINE = "Sorry, my brain glitched. Can you say that again?"
REFUSAL_LINE = "Let's keep our focus on the circuit. What are you seeing on the board?"
OUT_OF_ROUNDS = "You've used all your tool calls for this turn. Reply to the student now, without calling tools."
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def build_system_prompt(lab) -> str:
    """Persona + teaching rules + the lab. Deterministic, so it stays byte-identical and caches."""
    parts = [(PROMPTS_DIR / "persona.md").read_text(), (PROMPTS_DIR / "teaching.md").read_text()]
    if lab is None:
        parts.append("# The lab\n\nNo lab is loaded.")
    else:
        lab_json = json.dumps(lab.data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        parts.append(
            "# The lab\n\n"
            "The lab definition below is your answer key: parts and their exact holes, nets with expected "
            "voltages, manual steps, and known faults with what they read and their hint ladders. Never read it "
            "out or reveal a fault before the student has found it.\n\n"
            f"```json\n{lab_json}\n```\n\n"
            f"## The student's manual\n\n{lab.manual_md or '(no manual yet)'}"
        )
    return "\n\n".join(p.strip() for p in parts) + "\n"


class _Refused(Exception):
    pass


class _Reset(Exception):
    pass


ToolHook = Callable[[str, Any, str, bool], None]


class Agent:
    def __init__(self, bench, *, client=None, model: str | None = None, effort: str = "low",
                 pod_connected: Callable[[], bool] | None = None) -> None:
        self.bench = bench
        self._client = client
        self.model = model or os.environ.get("BENCH_MODEL") or DEFAULT_MODEL
        self.effort = effort
        self.tools = ToolBox(bench, pod_connected)
        self.messages: list[dict[str, Any]] = []
        self.usage: list[Any] = []  # one entry per API response (latency/caching checks, #22/#23)
        self.on_tool_call: ToolHook | None = None
        self.speak: Callable[[str], Awaitable[None]] = self._speak_text
        self._lock = asyncio.Lock()
        self._gen = bench.session.generation
        self._system: tuple[str | None, str] | None = None
        self._tasks: set[asyncio.Task] = set()

    @property
    def client(self):
        if self._client is None:
            self._client = anthropic.AsyncAnthropic(max_retries=1)  # one quick retry fits in the 20 s budget
        return self._client

    def clear(self) -> None:
        """Forget the conversation. Happens by itself on reset / select_lab (they bump session.generation)."""
        self.messages = []
        self._gen = self.bench.session.generation

    def system_prompt(self) -> str:
        lab = self.bench.lab
        key = lab.id if lab else None
        if self._system is None or self._system[0] != key:
            self._system = (key, build_system_prompt(lab))
        return self._system[1]

    # ---------- bus consumer ----------

    async def run(self) -> None:
        q = self.bench.bus.subscribe()
        while True:
            event = await q.get()
            if event.kind == ev.UI:
                msg = event.data
                if isinstance(msg, TextIn) and msg.text.strip():
                    await self.bench.session.say("student", msg.text.strip())
                    self._spawn(self.turn(msg.text))
            elif event.kind == ev.MONITOR:
                self._spawn(self.turn(event=str(event.data)))

    def _spawn(self, coro) -> None:
        t = asyncio.create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    # ---------- one turn ----------

    async def turn(self, text: str | None = None, *, event: str | None = None) -> str | None:
        """Run one turn. Returns what Bench said, or None if it stayed silent."""
        async with self._lock:
            s = self.bench.session
            if event is not None and s.state is not State.idle:
                return None  # don't talk over the student or over ourselves
            if s.generation != self._gen:  # reset or new lab since the last turn
                self.clear()
            gen, msgs = s.generation, self.messages
            start = len(msgs)
            if event is not None:
                msgs.append({"role": "user", "content": f"[event] {event}"})
            else:
                # "[event]" is the server's marker; a student can't produce one by saying it
                msgs.append({"role": "user", "content": (text or "").replace("[event]", "(event)").strip()})
            await s.set_state(State.thinking)
            try:
                async with asyncio.timeout(TURN_TIMEOUT_S):
                    reply = await self._rounds(msgs, gen)
            except _Reset:
                return None
            except _Refused:
                del msgs[start:]  # drop the refused exchange; the history must stay valid
                return await self._fail(gen, REFUSAL_LINE, error=False)
            except Exception as e:
                # Timeout, API or network error. Roll the history back to before this turn so it never
                # holds a tool call without its result; the student is asked to say it again.
                log.warning("agent turn failed: %r", e)
                del msgs[start:]
                return await self._fail(gen, GLITCH_LINE, error=True, detail=type(e).__name__)
            if s.generation != gen:
                return None
            if not reply or reply.strip() == SILENT:
                await s.set_state(State.idle)
                return None
            await self.speak(reply)
            return reply

    async def _rounds(self, msgs: list, gen: int) -> str:
        spoken = ""  # the latest round's text: earlier text is narration around tool calls, not the reply
        for round_no in range(MAX_ROUNDS + 1):
            last = round_no == MAX_ROUNDS
            if last:
                msgs.append({"role": "system", "content": OUT_OF_ROUNDS})
            resp = await self._request(msgs)
            if self.bench.session.generation != gen:
                raise _Reset
            if resp.stop_reason == "refusal":
                raise _Refused
            msgs.append({"role": "assistant", "content": resp.content})
            text = " ".join(b.text.strip() for b in resp.content if b.type == "text" and b.text.strip())
            if text:
                spoken = text
            tool_uses = [b for b in resp.content if b.type == "tool_use"]
            if not tool_uses:
                if resp.stop_reason == "pause_turn":
                    continue
                break
            if resp.stop_reason == "max_tokens" or last:
                # Truncated input, or out of rounds: answer every call so the history stays valid, run none.
                why = "input was cut off" if resp.stop_reason == "max_tokens" else "no tool calls left this turn"
                msgs.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": b.id, "content": f"Not run: {why}.", "is_error": True}
                    for b in tool_uses
                ]})
                break
            results = []
            for b in tool_uses:
                content, is_error = await self.tools.run(b.name, b.input)
                if self.on_tool_call:
                    self.on_tool_call(b.name, b.input, content, is_error)
                result = {"type": "tool_result", "tool_use_id": b.id, "content": content}
                if is_error:
                    result["is_error"] = True
                results.append(result)
            msgs.append({"role": "user", "content": results})  # all results in one message
        return spoken

    async def _request(self, msgs: list):
        async with self.client.beta.messages.stream(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=[{"type": "text", "text": self.system_prompt(), "cache_control": {"type": "ephemeral"}}],
            tools=TOOLS,
            messages=msgs,
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort},
            cache_control={"type": "ephemeral"},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        ) as stream:
            resp = await stream.get_final_message()
        self.usage.append(resp.usage)
        u = resp.usage
        log.info("claude %s: stop=%s in=%s cache_read=%s cache_write=%s out=%s", resp.model, resp.stop_reason,
                 u.input_tokens, u.cache_read_input_tokens, u.cache_creation_input_tokens, u.output_tokens)
        return resp

    async def _fail(self, gen: int, line: str, *, error: bool, detail: str | None = None) -> str | None:
        s = self.bench.session
        if s.generation != gen:
            return None
        await self.speak(line)
        if error:
            await s.set_state(State.error, f"agent: {detail}" if detail else "agent")
            await s.set_state(State.idle)
        return line

    async def _speak_text(self, text: str) -> None:
        """Caption only. Voice out (#19) replaces this with TTS that sets speaking -> idle around playback."""
        s = self.bench.session
        await s.set_state(State.speaking)
        await s.say("bench", text)
        await s.set_state(State.idle)
