"""Push-to-talk + Cartesia STT (#18).

The mic stays open and keeps the last 300 ms, so a clip starts just before the talk button went down
and the first word isn't clipped. Releasing the button sends the clip to Cartesia speech-to-text, puts
the transcript on screen, and hands it to the agent. Typed `text` from the UI never comes through here.

    cd server
    uv run python -m bench.voice_in --list-devices     # pick one, then MIC_DEVICE=<index or name> in .env
    uv run python -m bench.voice_in --test 4           # record 4 s, transcribe, print the timing

MIC_DEVICE: empty = the system default input, an index or a name substring from --list-devices, or
"off" for no mic (the talk button then just goes listening -> idle).
"""

import argparse
import asyncio
import collections
import io
import logging
import math
import os
import sys
import threading
import time
import wave
from collections.abc import Awaitable, Callable
from pathlib import Path

import numpy as np

from .protocol import State
from .session import Session

log = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
BLOCK = 800              # 50 ms per mic callback
PREROLL_S = 0.3          # audio kept from before the button went down
MIN_CLIP_S = 0.3         # a shorter press is a tap: ignore it
STT_MODEL = os.environ.get("BENCH_STT_MODEL", "ink-whisper")
STT_TIMEOUT_S = 6.0
CLIP_DIR = os.environ.get("BENCH_CLIP_DIR")  # set to a folder to keep every clip as a WAV (tuning, noise test)
MIC_OFF = {"off", "none"}  # not "0": that's a device index
DIDNT_CATCH = "I didn't catch that. Hold the button and say it again?"
NO_MIC_PERMISSION = (
    "the mic gave pure silence. On macOS, allow microphone access for your terminal app "
    "(System Settings > Privacy & Security > Microphone), then restart it"
)


def mic_device(value: str | None) -> int | str | None:
    """MIC_DEVICE -> what sounddevice wants: None (default input), an index, or a name substring."""
    value = (value or "").strip()
    if not value:
        return None
    return int(value) if value.isdigit() else value


def wav_bytes(pcm: np.ndarray, rate: int = SAMPLE_RATE) -> bytes:
    """Mono int16 samples -> a WAV file in memory."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.astype("<i2").tobytes())
    return buf.getvalue()


class Mic:
    """An always-open 16 kHz mono int16 input stream with a pre-roll ring buffer."""

    def __init__(self, device: int | str | None = None) -> None:
        self.device = device
        self._lock = threading.Lock()
        self._ring: collections.deque[np.ndarray] = collections.deque(maxlen=math.ceil(PREROLL_S * SAMPLE_RATE / BLOCK))
        self._clip: list[np.ndarray] | None = None
        self._held = 0  # samples recorded since start_clip, not counting the pre-roll
        self._stream = None

    def open(self) -> None:
        import sounddevice as sd

        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=BLOCK,
            device=self.device, callback=self._callback,
        )
        self._stream.start()
        info = sd.query_devices(self._stream.device)
        log.info("mic: %s", info["name"])

    def close(self) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None

    def _callback(self, indata, frames, time_info, status) -> None:  # PortAudio's thread
        block = indata[:, 0].copy()
        with self._lock:
            if self._clip is None:
                self._ring.append(block)
            else:
                self._clip.append(block)
                self._held += len(block)

    def start_clip(self, preroll: bool = True) -> None:
        with self._lock:
            self._clip = list(self._ring) if preroll else []
            self._ring.clear()
            self._held = 0

    def stop_clip(self) -> tuple[np.ndarray | None, float]:
        """The clip (pre-roll included) and how long the button was held, in seconds."""
        with self._lock:
            clip, self._clip = self._clip, None
            held, self._held = self._held / SAMPLE_RATE, 0
        if not clip:
            return None, held
        return np.concatenate(clip), held


class CartesiaSTT:
    """Batch speech-to-text: one short WAV clip in, its text out."""

    def __init__(self, model: str = STT_MODEL) -> None:
        self.model = model
        self._client = None

    async def __call__(self, wav: bytes) -> str:
        if self._client is None:
            from cartesia import AsyncCartesia

            self._client = AsyncCartesia(api_key=os.environ.get("CARTESIA_API_KEY"), timeout=STT_TIMEOUT_S, max_retries=1)
        r = await self._client.stt.transcribe(file=("clip.wav", wav, "audio/wav"), model=self.model, language="en")
        return (r.text or "").strip()


class VoiceIn:
    """Owns the talk button's listening -> transcribing leg. The hub calls press() and release()."""

    def __init__(
        self,
        session: Session,
        mic: Mic,
        stt: Callable[[bytes], Awaitable[str]],
        *,
        on_transcript: Callable[[str], Awaitable[object]],
        speak: Callable[[str], Awaitable[None]],
    ) -> None:
        self.session = session
        self.mic = mic
        self.stt = stt
        self.on_transcript = on_transcript  # the agent's turn
        self.speak = speak
        self.timings: list[float] = []  # seconds from button release to transcript ready
        self._tasks: set[asyncio.Task] = set()

    def press(self, barge_in: bool = False) -> None:
        """The button went down and the session is now listening. On barge-in the pre-roll holds Bench's own
        voice from the speaker, so the clip starts at the press instead."""
        self.mic.start_clip(preroll=not barge_in)

    def release(self) -> None:
        """The button came up while listening. Transcribes in the background so the bus keeps flowing."""
        released = time.monotonic()
        pcm, held = self.mic.stop_clip()
        t = asyncio.create_task(self._transcribe(pcm, held, released))
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    def cancel(self) -> None:
        """The button came up but the session left listening meanwhile (e.g. reset): drop the clip."""
        self.mic.stop_clip()

    async def _transcribe(self, pcm: np.ndarray | None, held: float, released: float) -> None:
        s = self.session
        if pcm is None or held < MIN_CLIP_S:
            log.info("talk button tap (%.2f s): ignored", held)
            await s.set_state(State.idle)
            return
        gen = s.generation
        await s.set_state(State.transcribing)
        if not pcm.any():
            log.warning(NO_MIC_PERMISSION)
        wav = wav_bytes(pcm)
        if CLIP_DIR:
            (Path(CLIP_DIR) / time.strftime("clip-%H%M%S.wav")).write_bytes(wav)
        try:
            text = (await asyncio.wait_for(self.stt(wav), STT_TIMEOUT_S)).strip()
            failed = None
        except Exception as e:
            log.warning("stt failed: %r", e)
            text, failed = "", type(e).__name__
        took = time.monotonic() - released
        self.timings.append(took)
        log.info("stt: %.1f s clip, transcript %.2f s after release: %r", len(pcm) / SAMPLE_RATE, took, text)
        s.record("stt", ms=round(took * 1000), clip_s=round(len(pcm) / SAMPLE_RATE, 2), text=text, failed=failed)
        if s.generation != gen or s.state is not State.transcribing:
            return  # reset, new lab, or the student pressed again: drop this clip
        if not text:
            await self.speak(DIDNT_CATCH)
            if failed:
                await s.set_state(State.error, f"stt: {failed}")
                await s.set_state(State.idle)
            return
        await s.say("student", text)
        await self.on_transcript(text)


# ---------- command line: check the mic and STT without the rest of Bench ----------

def _list_devices() -> None:
    import sounddevice as sd

    default_in = sd.default.device[0]
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            mark = "*" if i == default_in else " "
            print(f"{mark} {i:2d}  {d['name']}  ({d['max_input_channels']} in, {d['default_samplerate']:.0f} Hz)")
    print("* = system default. Set MIC_DEVICE=<index or part of the name> in .env to pick another.")


async def _test(seconds: float) -> None:
    mic = Mic(mic_device(os.environ.get("MIC_DEVICE")))
    mic.open()
    await asyncio.sleep(PREROLL_S)
    print(f"Recording {seconds:g} s: say something.")
    mic.start_clip()
    await asyncio.sleep(seconds)
    pcm, _ = mic.stop_clip()
    mic.close()
    peak = int(np.abs(pcm.astype(np.int32)).max()) if pcm is not None else 0
    print(f"Got {len(pcm) / SAMPLE_RATE:.2f} s, peak level {peak} of 32767.")
    if not peak:
        print(f"Warning: {NO_MIC_PERMISSION}.")
    t0 = time.monotonic()
    text = await CartesiaSTT()(wav_bytes(pcm))
    print(f"Transcript ({time.monotonic() - t0:.2f} s, {STT_MODEL}): {text!r}")


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    p = argparse.ArgumentParser(prog="bench.voice_in", description="Check the mic and Cartesia speech-to-text.")
    p.add_argument("--list-devices", action="store_true", help="list input devices")
    p.add_argument("--test", type=float, metavar="SECONDS", help="record this long, then transcribe")
    args = p.parse_args()
    if args.list_devices:
        _list_devices()
    elif args.test:
        asyncio.run(_test(args.test))
    else:
        p.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
