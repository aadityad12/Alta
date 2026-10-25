"""Cartesia TTS playback (#19).

One warm Cartesia websocket; each utterance is one context, fed sentence by sentence as the agent
writes them, and its PCM is played through an always-open sounddevice output stream as it arrives.
stop() (barge-in, reset) silences the speaker at once and drops the rest of what that turn was saying.

    cd server
    uv run python -m bench.voice_out "Row 10 reads 1.92 V, so the LED is on."   # hear it + timing
    uv run python -m bench.voice_out --voice woman "Row 10 reads 1.92 V."
    uv run python -m bench.voice_out --list-devices

    uv run python -m bench.voice_out --audition            # the same ALTA lines in 9 voices, to pick one
    uv run python -m bench.voice_out --audition --emotion content

Env: BENCH_VOICE (man = Gavin, the default; woman = Maya; or --voice), CARTESIA_VOICE_ID (any other
voice; beats BENCH_VOICE), BENCH_VOICE_SPEED (0.6-1.5),
BENCH_VOICE_EMOTION (empty = inferred from the text; e.g. content, calm, happy), BENCH_TTS_MODEL,
SPEAKER_DEVICE (empty = system default output, index or name substring).
"""

import argparse
import asyncio
import collections
import logging
import os
import re
import sys
import threading
import time
from collections.abc import AsyncIterator, Iterable
from pathlib import Path

import numpy as np

from .protocol import State
from .session import Session

log = logging.getLogger(__name__)

TTS_RATE = 24_000
TTS_MODEL = os.environ.get("BENCH_TTS_MODEL", "sonic-3.5")
# The two voices to choose from before a session (#36): BENCH_VOICE=man|woman or --voice. Picked by ear.
VOICES = {"man": ("Gavin", "f4a3a8e4-694c-4c45-9ca0-27caf97901b5"),
          "woman": ("Maya", "cbaf8084-f009-4838-a096-07ee2e6612b1")}
DEFAULT_CHOICE = "man"
# Candidates for #36: Cartesia's list of voices that respond best to emotion, plus the old placeholder.
AUDITION_VOICES = {
    "Parker": "30894953-bcce-41fe-892c-15ce19c843ff",
    "Kyle": "c961b81c-a935-4c17-bfb3-ba2239de8c2f", "Jace": "6776173b-fd72-460d-89b3-d85812ee518d",
    "Leo": "0834f3df-e650-4766-a20c-5a93a43aa6e3", "Gavin": "f4a3a8e4-694c-4c45-9ca0-27caf97901b5",
    "Tessa": "6ccbfb76-1fc6-48f7-b71d-91ac6298247b", "Maya": "cbaf8084-f009-4838-a096-07ee2e6612b1",
    "Dana": "cc00e582-ed66-4004-8336-0175b85c85f6", "Marian": "26403c37-80c1-4a1a-8692-540551ca2ae5",
}
AUDITION_LINES = ("Okay, let's find where the power stops. Put the yellow probe in row 10, right where the "
                  "resistor meets the LED. Nice, that's it! Row 10 is at about 1.9 volts now, so current's "
                  "flowing, and you found it yourself.")
OUTPUT_FORMAT = {"container": "raw", "encoding": "pcm_s16le", "sample_rate": TTS_RATE}
TTS_TIMEOUT_S = 10.0
TTS_REFRESH_S = 60.0  # Cartesia closes an idle websocket ("connection idle timeout"): reopen it before that
TTS_REFRESH_POLL_S = 5.0


# ---------- text ----------

_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]")
_MARKDOWN = re.compile(r"[*_`#]+")
_HEDGE = r"(?:about|around|roughly|nearly|almost|approximately|~)\s*"
_VOLTS = re.compile(rf"(?<![\w.])({_HEDGE})?(\d+(?:\.\d+)?)\s?(mV|V)\b")
_OHMS = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s?([kM]?)\s?(?:Ω|ohms?\b)")
_STRIP = re.compile(r"\b(?:row\s+)?(\d{1,2}):[a-j]-[a-j]\b")
_HOLE = re.compile(r"\b(?:row\s+)?(\d{1,2})([a-j])\b")
_RAIL = re.compile(r"\brail:[aj]?([+-])")  # CONTRACTS §4: rail:a+ rail:a- rail:j+ rail:j-


def _num(x: float) -> str:
    return str(int(x)) if x == int(x) else f"{x:g}"


def _volts(m: re.Match) -> str:
    hedge, value, unit = m.group(1), float(m.group(2)), m.group(3)
    decimals = len(m.group(2).partition(".")[2])
    if unit == "mV":
        if value < 100:
            return f"{hedge or ''}{_num(value)} millivolts"
        value, decimals = value / 1000, 2  # 1900 mV -> about 1.9 volts
    rounded = round(value, 1)
    about = "about " if hedge or (decimals > 1 and rounded != value) else ""
    return f"{about}{_num(rounded)} {'volt' if rounded == 1 else 'volts'}"


def _ohms(m: re.Match) -> str:
    value, prefix = m.group(1), m.group(2)
    unit = {"": "ohms", "k": "kilohms", "M": "megohms"}[prefix]
    return f"{value} {unit[:-1] if value == '1' else unit}"


def normalize(text: str) -> str:
    """What ALTA writes -> what the TTS should say: "1.92 V" -> "about 1.9 volts", "10c" -> "row 10, column c"."""
    t = _EMOJI.sub("", text)
    t = _MARKDOWN.sub("", t)
    t = _VOLTS.sub(_volts, t)
    t = _OHMS.sub(_ohms, t)
    t = t.replace("Ω", " ohms")
    t = _STRIP.sub(r"row \1", t)
    t = _HOLE.sub(r"row \1, column \2", t)
    t = _RAIL.sub(lambda m: "the plus rail" if m.group(1) == "+" else "the minus rail", t)
    t = re.sub(r"\bLEDs\b", "L E Ds", t)
    t = re.sub(r"\bLED\b", "L E D", t)
    t = re.sub(r"\bALTA\b", "Alta", t)  # the name is said as a word, not spelled out
    return re.sub(r"\s{2,}", " ", t).strip()


class SentenceSplitter:
    """Feed text deltas as Claude streams them; get back each sentence once it's complete."""

    _END = re.compile(r"[.!?]+[\"')\]]*\s+")

    def __init__(self) -> None:
        self.buf = ""

    def feed(self, delta: str) -> list[str]:
        self.buf += delta
        out = []
        while m := self._END.search(self.buf):
            sentence, self.buf = self.buf[: m.end()].strip(), self.buf[m.end():]
            if sentence:
                out.append(sentence)
        return out

    def flush(self) -> list[str]:
        rest, self.buf = self.buf.strip(), ""
        return [rest] if rest else []


def sentences_of(text: str) -> list[str]:
    sp = SentenceSplitter()
    return sp.feed(text) + sp.flush()


async def _aiter(items: Iterable[str]) -> AsyncIterator[str]:
    for x in items:
        yield x


# ---------- audio ----------

class Player:
    """An always-open 24 kHz mono int16 output stream playing whatever is queued; clear() silences it at once."""

    def __init__(self, device: int | str | None = None) -> None:
        self.device = device
        self._lock = threading.Lock()
        self._buf: collections.deque[np.ndarray] = collections.deque()
        self._pos = 0
        self._stream = None

    def open(self) -> None:
        import sounddevice as sd

        self._stream = sd.OutputStream(
            samplerate=TTS_RATE, channels=1, dtype="int16", device=self.device, callback=self._callback, latency="low",
        )
        self._stream.start()
        log.info("speaker: %s", sd.query_devices(self._stream.device)["name"])

    def close(self) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None

    @property
    def latency(self) -> float:
        """Seconds between handing audio to the device and hearing it."""
        return float(self._stream.latency) if self._stream is not None else 0.0

    def _callback(self, outdata, frames, time_info, status) -> None:  # PortAudio's thread
        out = outdata[:, 0]
        n = 0
        with self._lock:
            while n < frames and self._buf:
                block = self._buf[0]
                take = min(frames - n, len(block) - self._pos)
                out[n:n + take] = block[self._pos:self._pos + take]
                n += take
                self._pos += take
                if self._pos == len(block):
                    self._buf.popleft()
                    self._pos = 0
        out[n:] = 0

    def write(self, pcm: np.ndarray) -> None:
        with self._lock:
            self._buf.append(pcm)

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()
            self._pos = 0

    def pending(self) -> int:
        """Samples queued but not yet played."""
        with self._lock:
            return sum(len(b) for b in self._buf) - self._pos


# ---------- speaker ----------

def pick_voice() -> tuple[str, str]:
    """(name, Cartesia voice id): CARTESIA_VOICE_ID if set, else BENCH_VOICE (man|woman), else the man's."""
    if vid := os.environ.get("CARTESIA_VOICE_ID", "").strip():
        return "custom", vid
    choice = os.environ.get("BENCH_VOICE", "").strip().lower() or DEFAULT_CHOICE
    if choice not in VOICES:
        log.warning("BENCH_VOICE=%r isn't one of %s; using %s", choice, "|".join(VOICES), DEFAULT_CHOICE)
        choice = DEFAULT_CHOICE
    return VOICES[choice]


class Speaker:
    """Speaks utterances one at a time. Each sentence is captioned as it's sent, and `speaking` starts with
    the first audio. An utterance is muted by stop(), and so is anything else from the same owner (one
    agent turn), so a turn that's still writing can't start talking again after the student cut in."""

    def __init__(self, session: Session, player: Player, *, client=None, voice_id: str | None = None,
                 model: str = TTS_MODEL, speed: float | None = None, emotion: str | None = None) -> None:
        self.session = session
        self.player = player
        self.voice_name, self.voice_id = ("custom", voice_id) if voice_id else pick_voice()
        self.model = model
        if speed is None and os.environ.get("BENCH_VOICE_SPEED"):
            speed = float(os.environ["BENCH_VOICE_SPEED"])
        self.speed = speed
        self.emotion = emotion if emotion is not None else (os.environ.get("BENCH_VOICE_EMOTION", "").strip() or None)
        self.timings: list[float] = []  # seconds from the first text sent to its first audio heard
        self._client = client
        self._conn = None
        self._lock = asyncio.Lock()
        self._owner: object = None
        self._muted: object = None
        self._ctx = None
        self._recv: asyncio.Task | None = None
        self._used = time.monotonic()  # last time the websocket was opened or used

    async def connect(self):
        """Open (or reuse) the websocket. Called at startup so the first reply doesn't pay for the handshake."""
        if self._conn is None:
            if self._client is None:
                from cartesia import AsyncCartesia

                self._client = AsyncCartesia(api_key=os.environ.get("CARTESIA_API_KEY"))
            self._conn = await self._client.tts.websocket_connect().enter()
            self._used = time.monotonic()
        return self._conn

    async def keep_fresh(self) -> None:
        """Runs for the app's lifetime: reopen the websocket once it's gone TTS_REFRESH_S unused, so Cartesia's
        idle timeout never closes it under us and the next reply still doesn't pay for the handshake."""
        while True:
            await asyncio.sleep(TTS_REFRESH_POLL_S)
            if self._conn is None or self._lock.locked() or time.monotonic() - self._used < TTS_REFRESH_S:
                continue
            async with self._lock:
                await self.close()
                try:
                    await self.connect()
                except Exception as e:
                    log.warning("tts reconnect failed (%r); will retry on the next reply", e)

    async def close(self) -> None:
        if self._conn is not None:
            try:
                await self._conn.close()
            except Exception:
                pass
            self._conn = None

    def stop(self) -> None:
        """Barge-in or reset: silence now, and drop the rest of what the current owner was going to say."""
        self._muted = self._owner
        self.player.clear()
        if self._recv is not None:
            self._recv.cancel()
        if self._ctx is not None:
            ctx, self._ctx = self._ctx, None
            asyncio.ensure_future(_quietly(ctx.cancel()))

    async def say(self, text: str) -> None:
        """One complete line (fallback lines, "I didn't catch that"). Ends in idle."""
        await self.speak(_aiter(sentences_of(text)))

    async def speak(self, sentences: AsyncIterator[str], *, owner: object = None, end_idle: bool = True) -> str:
        """Speak sentences as they arrive. Returns what was said. end_idle=False leaves `speaking` for the caller."""
        owner = owner if owner is not None else object()
        async with self._lock:
            s = self.session
            gen = s.generation
            self._owner = owner
            said: list[str] = []
            ctx = None
            sent_at: list[float] = []
            retried = False
            async for sentence in sentences:
                if self._muted is owner or s.generation != gen:
                    continue  # keep draining so the writer never blocks
                if not said:
                    ctx = await self._open_context()
                    if ctx is None and not await self._enter_speaking(owner):  # captions only
                        continue
                    if ctx is not None:
                        self._recv = asyncio.create_task(self._receive(ctx, owner, sent_at))
                said.append(sentence)
                await s.say("bench", " ".join(said), final=False)
                if ctx is not None:
                    try:
                        await ctx.push(normalize(sentence) + " ")
                        if not sent_at:
                            sent_at.append(time.monotonic())
                            s.record("first_sentence")
                    except Exception as e:
                        ctx = None if retried else await self._reconnect(e, said, owner, sent_at)
                        retried = True
                        if ctx is None:
                            log.warning("tts push failed: %r (captions only from here)", e)
                            await s.health.down("voice", f"tts: {type(e).__name__}")
                            await self._enter_speaking(owner)  # still speaking -> idle, like any reply
            if said:
                await s.say("bench", " ".join(said))
            if ctx is not None and self._muted is not owner:
                try:
                    await ctx.no_more_inputs()
                except Exception as e:
                    log.warning("tts: %r", e)
            if self._recv is not None:
                try:
                    await self._recv
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    log.warning("tts receive failed: %r", e)
                    await s.health.down("voice", f"tts: {type(e).__name__}")
                    self._conn = None  # it may be dead: the next reply opens a fresh one
                self._recv = None
            self._ctx = None
            if said and s.state is State.thinking and s.generation == gen and self._muted is not owner:
                await self._enter_speaking(owner)  # no audio ever came: end like a spoken reply, not stuck thinking
            while self.player.pending() and self._muted is not owner:
                await asyncio.sleep(0.02)
            if self._muted is not owner:
                await asyncio.sleep(self.player.latency)  # the last chunk is still in the device
            if end_idle and s.state is State.speaking and s.generation == gen and self._muted is not owner:
                await s.set_state(State.idle)
            return " ".join(said)

    async def _reconnect(self, e: Exception, said: list[str], owner: object, sent_at: list[float]):
        """A push failed: the websocket died under us (Cartesia closed it, or the network blipped). Open a fresh
        one and resend what this utterance has said so far. Returns the new context, or None."""
        log.warning("tts push failed: %r; reconnecting", e)
        if self._recv is not None:
            self._recv.cancel()
            self._recv = None
        self._conn = None  # already dead: nothing to close
        ctx = await self._open_context()
        if ctx is None:
            return None
        self._recv = asyncio.create_task(self._receive(ctx, owner, sent_at))
        try:
            for sentence in said:
                await ctx.push(normalize(sentence) + " ")
        except Exception as e2:
            log.warning("tts push failed again: %r", e2)
            self._recv.cancel()
            self._recv = None
            self._conn = None
            return None
        if not sent_at:
            sent_at.append(time.monotonic())
            self.session.record("first_sentence")
        return ctx

    async def _open_context(self):
        try:
            conn = await self.connect()
            self._used = time.monotonic()
            gen = {k: v for k, v in (("speed", self.speed), ("emotion", self.emotion)) if v}
            kw = {"generation_config": gen} if gen else {}
            self._ctx = conn.context(
                model_id=self.model, voice={"id": self.voice_id}, output_format=OUTPUT_FORMAT, language="en",
                max_buffer_delay_ms=0,  # we send whole sentences: start each one right away (default waits 3 s)
                timeout=TTS_TIMEOUT_S, **kw,
            )
            return self._ctx
        except Exception as e:
            log.warning("tts unavailable: %r (captions only)", e)
            self._conn = None
            await self.session.health.down("voice", f"tts: {type(e).__name__}")
            return None

    async def _enter_speaking(self, owner: object) -> bool:
        s = self.session
        if s.state is State.speaking or await s.set_state(State.speaking):
            return True
        self._muted = owner  # the student is talking (or nothing asked us to speak): stay quiet
        return False

    async def _receive(self, ctx, owner: object, sent_at: list[float]) -> None:
        first = True
        async for ev in ctx.receive():
            if ev.type == "chunk":
                audio = ev.audio
                if not audio or self._muted is owner:
                    continue
                if first:
                    first = False
                    await self.session.health.ok("voice")
                    if not await self._enter_speaking(owner):
                        self.player.clear()
                        continue
                    if sent_at:
                        took = time.monotonic() - sent_at[0] + self.player.latency
                        self.timings.append(took)
                        log.info("tts: first audio %.0f ms after text ready (%s)", took * 1000, self.model)
                        self.session.record("first_audio", ms=round(took * 1000))
                self.player.write(np.frombuffer(audio, dtype="<i2"))
            elif ev.type == "error":
                log.warning("tts error: %s", getattr(ev, "error", ev))
                await self.session.health.down("voice", "tts error")
                return


async def _quietly(coro) -> None:
    try:
        await coro
    except Exception:
        pass


def output_device(value: str | None) -> int | str | None:
    value = (value or "").strip()
    if not value:
        return None
    return int(value) if value.isdigit() else value


# ---------- command line: hear a line without the rest of ALTA ----------

def _list_devices() -> None:
    import sounddevice as sd

    default_out = sd.default.device[1]
    for i, d in enumerate(sd.query_devices()):
        if d["max_output_channels"] > 0:
            print(f"{'*' if i == default_out else ' '} {i:2d}  {d['name']}")
    print("* = system default. Set SPEAKER_DEVICE=<index or part of the name> in .env to pick another.")


async def _say(text: str) -> None:
    session = Session(broadcast=_noop)
    session.state = State.thinking
    player = Player(output_device(os.environ.get("SPEAKER_DEVICE")))
    player.open()
    speaker = Speaker(session, player)
    t0 = time.monotonic()
    await speaker.connect()
    print(f"connected in {(time.monotonic() - t0) * 1000:.0f} ms · voice {speaker.voice_name} {speaker.voice_id}"
          f" · {speaker.model}")
    print(f"says: {' '.join(normalize(x) for x in sentences_of(text))}")
    await speaker.say(text)
    print(f"first audio {speaker.timings[0] * 1000:.0f} ms after text ready" if speaker.timings else "no audio")
    await speaker.close()
    player.close()


async def _audition(emotion: str | None) -> None:
    session = Session(broadcast=_noop)
    player = Player(output_device(os.environ.get("SPEAKER_DEVICE")))
    player.open()
    for name, voice_id in AUDITION_VOICES.items():
        speaker = Speaker(session, player, voice_id=voice_id, emotion=emotion)
        print(f"{name:<7} {voice_id}" + (f" · emotion {emotion}" if emotion else ""), flush=True)
        session.state = State.thinking
        await speaker.say(f"Hi, I'm {name}. {AUDITION_LINES}")
        await speaker.close()
        await asyncio.sleep(0.6)
    player.close()
    print("Pick one: CARTESIA_VOICE_ID=<id> in .env (and BENCH_VOICE_EMOTION if you used one).")


async def _noop(msg) -> None:
    pass


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    logging.basicConfig(level=logging.WARNING)
    p = argparse.ArgumentParser(prog="bench.voice_out", description="Hear ALTA's voice.")
    p.add_argument("text", nargs="?")
    p.add_argument("--list-devices", action="store_true")
    p.add_argument("--voice", choices=("man", "woman"), help="ALTA's voice (default: BENCH_VOICE from .env, else man)")
    p.add_argument("--audition", action="store_true", help="the same ALTA lines in each candidate voice")
    p.add_argument("--emotion", default=None, help="with --audition: e.g. content, calm, happy, enthusiastic")
    args = p.parse_args()
    if args.voice:
        os.environ["BENCH_VOICE"] = args.voice
    if args.list_devices:
        _list_devices()
    elif args.audition:
        asyncio.run(_audition(args.emotion))
    elif args.text:
        asyncio.run(_say(args.text))
    else:
        p.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
