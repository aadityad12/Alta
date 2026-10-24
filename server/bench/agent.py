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

Speech (#19, #22): with speak_stream set, every round is spoken sentence by sentence while Claude is
still writing it. ALTA speaks first: the reply comes before the tool calls that go with it, so when every
call in a round is one whose result can't change what ALTA says (SPEAK_FIRST_TOOLS: highlights,
ask_for_probe, record_diagnosis...), the turn ends right there, with no second round to wait for. Those
tool results are sent with the next user message, so the history stays append-only and valid. If a round
spoke and still needs another one (read_probes, look_at_board, a tool error), a system note says what the
student already heard, so it isn't repeated.

Latency (#22): a student turn with no text after FILLER_S gets a short "Mm, let me check." and the
prompt cache is pre-warmed for the current lab (keep_warm).
"""

import asyncio
import itertools
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import anthropic

from . import bus as ev
from .protocol import State, TextIn
from .tools import TOOLS, ToolBox
from .voice_out import SentenceSplitter

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FAST_BETA = "fast-mode-2026-02-01"  # BENCH_SPEED=fast: Opus fast mode (Claude API only, 2x price)
MAX_ROUNDS = 6
TURN_TIMEOUT_S = 20.0
MAX_TOKENS = 16000  # thinking counts against this too; replies themselves are a sentence or two
SILENT = "<silent>"
GLITCH_LINE = "Sorry, my brain glitched. Can you say that again?"
REFUSAL_LINE = "Let's keep our focus on the circuit. What are you seeing on the board?"
OUT_OF_ROUNDS = "You've used all your tool calls for this turn. Reply to the student now, without calling tools."
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
# Tools whose result can't change what ALTA says: a round that spoke and called only these ends the turn.
SPEAK_FIRST_TOOLS = {"ask_for_probe", "highlight", "clear_highlights", "highlight_schematic", "show_manual_step",
                     "record_diagnosis"}
ALREADY_SAID = "The student already heard you say: \"{}\" Don't repeat it. Say only what's new, or reply {}."
# Text written before a tool call can come back as a hidden progress note instead of text; then Claude thinks
# it already spoke and writes a report about the student. Say plainly that nothing was heard.
NOTHING_SAID = "The student hasn't heard anything from you this turn. What you write next is spoken to them directly."
FILLER_S = 1.5  # BENCH_FILLER_S; 0 = off
FILLER_LINES = ("Mm, let me check.", "Okay, one sec.", "Hmm, let me look.")
WARM_EVERY_S = 270  # the cache lives 5 minutes; re-warm a bit before that when nothing else has used it


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
                 speed: str | None = None, pod_connected: Callable[[], bool] | None = None) -> None:
        self.bench = bench
        self._client = client
        self.model = model or os.environ.get("BENCH_MODEL") or DEFAULT_MODEL
        self.effort = effort
        self.speed = speed if speed is not None else (os.environ.get("BENCH_SPEED", "").strip() or None)
        self.tools = ToolBox(bench, pod_connected)
        self.messages: list[dict[str, Any]] = []
        self.usage: list[Any] = []  # one entry per API response (latency/caching checks, #22/#23)
        self.on_tool_call: ToolHook | None = None
        self.speak: Callable[[str], Awaitable[None]] = self._speak_text
        # Speaker.speak (#19): (sentences, owner=, end_idle=) -> what was said. None = speak whole replies.
        self.speak_stream: Callable[..., Awaitable[str]] | None = None
        self._live: list[_LiveSpeech] = []
        self._text_seen = False  # this turn's first text delta seen yet (latency mark, #22)
        self._reply_live = False
        self._lock = asyncio.Lock()
        self._gen = bench.session.generation
        self._system: tuple[str | None, str] | None = None
        self._tasks: set[asyncio.Task] = set()
        self.filler_s = float(os.environ.get("BENCH_FILLER_S", FILLER_S))
        self._fillers = itertools.cycle(FILLER_LINES)
        self._filler_spoke = False
        self._last_request = 0.0  # time.monotonic() of the last request (or pre-warm) that used the cache
        self._warm_key: tuple | None = None

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
        """Run one turn. Returns what ALTA said, or None if it stayed silent."""
        async with self._lock:
            s = self.bench.session
            if event is not None and s.state is not State.idle:
                return None  # don't talk over the student or over ourselves
            if s.generation != self._gen:  # reset or new lab since the last turn
                self.clear()
            gen, msgs = s.generation, self.messages
            self.tools.new_turn(None if event is not None else text)
            s.record("turn", source="event" if event is not None else "student", text=event if event is not None else text)
            self._text_seen = False
            # "[event]" is the server's marker; a student can't produce one by saying it
            said = f"[event] {event}" if event is not None else (text or "").replace("[event]", "(event)").strip()
            start, kept = self._add_user(msgs, said)
            await s.set_state(State.thinking)
            self._live, self._reply_live, self._owner = [], False, object()
            self._filler_spoke = False
            filler = self._start_filler(gen) if event is None else None
            try:
                async with asyncio.timeout(TURN_TIMEOUT_S):
                    reply = await self._rounds(msgs, gen)
            except _Reset:
                return None
            except _Refused:
                self._rollback(msgs, start, kept)  # drop the refused exchange; the history must stay valid
                await self._end_filler(filler)
                return await self._fail(gen, REFUSAL_LINE, error=False)
            except Exception as e:
                # Timeout, API or network error. Roll the history back to before this turn so it never
                # holds a tool call without its result; the student is asked to say it again.
                log.warning("agent turn failed: %r", e)
                await self.bench.session.health.down("ai", type(e).__name__)
                self._rollback(msgs, start, kept)
                await self._end_filler(filler)
                return await self._fail(gen, GLITCH_LINE, error=True, detail=type(e).__name__)
            finally:
                if self.bench.session.generation != gen:
                    await self._end_filler(filler)
            await self._end_filler(filler)
            if s.generation != gen:
                return None
            await self._finish_live()
            s.record("turn_end", reply=reply, silent=not reply or reply.strip() == SILENT)
            if not reply or reply.strip() == SILENT:
                if s.state is State.thinking or (self._filler_spoke and s.state is State.speaking):
                    await s.set_state(State.idle)
                return None
            if self._reply_live:
                if s.state is State.speaking and s.generation == gen:
                    await s.set_state(State.idle)  # unless the student cut in: then they're talking
            else:
                await self.speak(reply)
            return reply

    @staticmethod
    def _add_user(msgs: list, text: str) -> tuple[int, int | None]:
        """Append the user's message. If the history ends in tool results that haven't been sent yet (a
        speak-first round ended the last turn), the text joins that message: two user messages in a row
        would be a 400. Returns how to roll it back: (len(msgs) before, len of the joined content or None)."""
        if msgs and msgs[-1]["role"] == "user" and isinstance(msgs[-1]["content"], list):
            kept = len(msgs[-1]["content"])
            msgs[-1]["content"].append({"type": "text", "text": text})
            return len(msgs), kept
        msgs.append({"role": "user", "content": text})
        return len(msgs) - 1, None

    @staticmethod
    def _rollback(msgs: list, start: int, kept: int | None) -> None:
        del msgs[start:]
        if kept is not None:
            del msgs[-1]["content"][kept:]

    def _start_filler(self, gen: int) -> asyncio.Task | None:
        """After filler_s with no text from Claude, say a short "let me check" so the silence isn't dead."""
        if not self.speak_stream or self.filler_s <= 0:
            return None
        owner = self._owner

        async def filler():
            await asyncio.sleep(self.filler_s)
            s = self.bench.session
            if self._text_seen or s.state is not State.thinking or s.generation != gen:
                return
            self._filler_spoke = True
            s.record("filler")
            await self.speak_stream(_lines([next(self._fillers)]), owner=owner, end_idle=False)

        return asyncio.create_task(filler())

    async def _end_filler(self, task: asyncio.Task | None) -> None:
        """Cancel the filler if it hasn't started talking; if it has, let it finish its line."""
        if task is None:
            return
        if not self._filler_spoke:
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.warning("filler failed: %r", e)

    async def _finish_live(self) -> None:
        tasks = [l.task for l in self._live if l.task]
        self._live = []
        for t in tasks:
            try:
                await t
            except Exception as e:
                log.warning("speech failed: %r", e)

    async def _rounds(self, msgs: list, gen: int) -> str:
        said: list[str] = []  # every round's text: ALTA says all of it, in order
        told = False  # NOTHING_SAID sent this turn
        for round_no in range(MAX_ROUNDS + 1):
            last = round_no == MAX_ROUNDS
            if last:
                msgs.append({"role": "system", "content": OUT_OF_ROUNDS})
            live = _LiveSpeech(self.speak_stream, self._owner) if self.speak_stream else None
            if live:
                self._live.append(live)
            resp = await self._request(msgs, live)
            if self.bench.session.generation != gen:
                raise _Reset
            if resp.stop_reason == "refusal":
                raise _Refused
            msgs.append({"role": "assistant", "content": resp.content})
            text = " ".join(b.text.strip() for b in resp.content if b.type == "text" and b.text.strip())
            if text and text != SILENT:
                said.append(text)
                self._reply_live = self._reply_live or live is not None
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
            results, failed = [], False
            for b in tool_uses:
                content, is_error = await self.tools.run(b.name, b.input)
                self.bench.session.record("tool", name=b.name, input=b.input, error=content if is_error else None)
                if self.on_tool_call:
                    self.on_tool_call(b.name, b.input, content, is_error)
                result = {"type": "tool_result", "tool_use_id": b.id, "content": content}
                if is_error:
                    result["is_error"] = True
                    failed = True
                results.append(result)
            msgs.append({"role": "user", "content": results})  # all results in one message
            if text and text != SILENT and not failed and all(b.name in SPEAK_FIRST_TOOLS for b in tool_uses):
                break  # spoke first, and nothing it called can change that: done. Results go with the next message.
            if said:
                msgs.append({"role": "system", "content": ALREADY_SAID.format(" ".join(said), SILENT)})
            elif not told and all(b.name in SPEAK_FIRST_TOOLS for b in tool_uses):
                msgs.append({"role": "system", "content": NOTHING_SAID})
                told = True
        return " ".join(said)

    async def _request(self, msgs: list, live: "_LiveSpeech | None" = None):
        t0, first = time.monotonic(), None
        async with self.client.beta.messages.stream(
            **self._settings(),
            max_tokens=MAX_TOKENS,
            messages=msgs,
            cache_control={"type": "ephemeral"},
            fallbacks="default",
        ) as stream:
            try:
                async for event in stream:  # read as it streams: latency marks (#22) and live speech (#19)
                    if first is None:
                        first = time.monotonic()
                    if event.type == "text":
                        if not self._text_seen:
                            self._text_seen = True
                            self.bench.session.record("first_text")
                        if live is not None:
                            live.feed(event.text)
            finally:
                if live is not None:
                    live.end()
            resp = await stream.get_final_message()
        self.usage.append(resp.usage)
        self._last_request = time.monotonic()
        await self.bench.session.health.ok("ai")
        u = resp.usage
        self.bench.session.record(
            "claude", ms=round((time.monotonic() - t0) * 1000), ttft_ms=round((first - t0) * 1000) if first else None,
            stop=resp.stop_reason, model=resp.model, input=u.input_tokens, output=u.output_tokens,
            cache_read=u.cache_read_input_tokens, cache_write=u.cache_creation_input_tokens)
        log.info("claude %s: stop=%s in=%s cache_read=%s cache_write=%s out=%s blocks=%s", resp.model, resp.stop_reason,
                 u.input_tokens, u.cache_read_input_tokens, u.cache_creation_input_tokens, u.output_tokens,
                 ",".join(b.type for b in resp.content if b.type != "thinking"))
        return resp

    def _settings(self) -> dict[str, Any]:
        """Everything that's rendered into the cached prefix, shared by real requests and the pre-warm."""
        fast = self.speed == "fast"
        return {
            "model": self.model,
            "system": [{"type": "text", "text": self.system_prompt(), "cache_control": {"type": "ephemeral"}}],
            "tools": TOOLS,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self.effort},
            "betas": [FALLBACK_BETA, FAST_BETA] if fast else [FALLBACK_BETA],
            **({"speed": "fast"} if fast else {}),
        }

    async def prewarm(self) -> None:
        """Write the tools + system prompt to the prompt cache now (max_tokens=0: nothing generated), so the
        first turn with this lab doesn't pay for it."""
        t0 = time.monotonic()
        resp = await self.client.beta.messages.create(
            **self._settings(), max_tokens=0, messages=[{"role": "user", "content": "warmup"}])
        self._last_request = time.monotonic()
        await self.bench.session.health.ok("ai")
        u = resp.usage
        log.info("prompt cache warmed in %.0f ms (write %s, read %s)", (time.monotonic() - t0) * 1000,
                 u.cache_creation_input_tokens, u.cache_read_input_tokens)

    async def keep_warm(self) -> None:
        """Runs for the app's lifetime: warm on start and on a new lab, and again before the cache expires
        if nothing else has used it (judges come and go; the first question after a gap shouldn't be slow)."""
        while True:
            key = (self.bench.session.lab_id, self.model, self.speed, self.effort)
            if self.bench.lab and (key != self._warm_key or time.monotonic() - self._last_request > WARM_EVERY_S):
                try:
                    await self.prewarm()
                    self._warm_key = key
                except Exception as e:
                    log.warning("cache pre-warm failed: %r", e)
                    await self.bench.session.health.down("ai", f"pre-warm: {type(e).__name__}")
                    await asyncio.sleep(30)
            await asyncio.sleep(2)

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


async def _lines(items):
    for item in items:
        yield item


class _LiveSpeech:
    """One round's text, handed to speak_stream a sentence at a time as Claude writes it."""

    def __init__(self, speak_stream: Callable[..., Awaitable[str]], owner: object) -> None:
        self._speak, self._owner = speak_stream, owner
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._split = SentenceSplitter()
        self._held: str | None = ""  # the start of the text, until it can't be SILENT any more
        self.task: asyncio.Task | None = None

    def feed(self, delta: str) -> None:
        if self._held is not None:
            self._held += delta
            if SILENT.startswith(self._held.strip()):
                return
            delta, self._held = self._held, None
        for sentence in self._split.feed(delta):
            self._put(sentence)

    def end(self) -> None:
        if self._held is not None:
            held, self._held = self._held.strip(), None
            if held and held != SILENT:
                self._split.feed(held)
        for sentence in self._split.flush():
            self._put(sentence)
        self._queue.put_nowait(None)

    def _put(self, sentence: str) -> None:
        if self.task is None:
            self.task = asyncio.create_task(self._speak(self._sentences(), owner=self._owner, end_idle=False))
        self._queue.put_nowait(sentence)

    async def _sentences(self):
        while (sentence := await self._queue.get()) is not None:
            yield sentence
