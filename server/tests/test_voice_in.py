import asyncio
import io
import wave

import numpy as np

from bench import bus as ev
from bench.bus import Event
from bench.protocol import State
from bench.voice_in import BLOCK, DIDNT_CATCH, SAMPLE_RATE, Mic, VoiceIn, wav_bytes

from .test_agent import make, of, states


class FakeMic:
    def __init__(self, held=1.0):
        self.held = held
        self.recording = False

    def start_clip(self, preroll=True):
        self.recording, self.preroll = True, preroll

    def stop_clip(self):
        was, self.recording = self.recording, False
        if not was:
            return None, 0.0
        return np.full(int((self.held + 0.3) * SAMPLE_RATE), 100, dtype=np.int16), self.held


class FakeSTT:
    def __init__(self, reply="", delay=0.0):
        self.reply, self.delay, self.clips = reply, delay, []

    async def __call__(self, wav):
        self.clips.append(wav)
        await asyncio.sleep(self.delay)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def setup(reply="", held=1.0, delay=0.0):
    agent, _, sent = make()
    turns = []

    async def on_transcript(text):
        turns.append(text)

    stt = FakeSTT(reply, delay)
    voice = VoiceIn(agent.bench.session, FakeMic(held), stt, on_transcript=on_transcript, speak=agent.speak)
    agent.bench.voice = voice
    return agent.bench, voice, stt, sent, turns


async def talk(bench, voice, between=None):
    await bench.handle(Event(ev.PTT, True))
    await bench.handle(Event(ev.PTT, False))
    if between:
        await between()
    await asyncio.gather(*voice._tasks)


def test_speech_becomes_a_student_transcript_and_an_agent_turn():
    bench, voice, stt, sent, turns = setup("Why won't my LED light up?")
    asyncio.run(talk(bench, voice))
    assert states(sent) == ["listening", "transcribing"]  # the agent's turn takes it from here
    assert of(sent, "transcript") == [{"type": "transcript", "role": "student", "text": "Why won't my LED light up?", "final": True}]
    assert turns == ["Why won't my LED light up?"]
    assert len(stt.clips) == 1 and stt.clips[0][:4] == b"RIFF"
    assert len(voice.timings) == 1


def test_a_tap_is_ignored():
    bench, voice, stt, sent, turns = setup("hi", held=0.2)
    asyncio.run(talk(bench, voice))
    assert states(sent) == ["listening", "idle"]
    assert stt.clips == [] and turns == [] and not of(sent, "transcript")


def test_a_mic_that_died_mid_press_says_didnt_catch_that_instead_of_going_quiet():
    """Seen on the real run: Bluetooth earbuds dropped, the mic stream stopped, and every press was a silent 0 s 'tap'."""
    bench, voice, stt, sent, turns = setup("hi", held=0.0)

    async def go():
        await bench.handle(Event(ev.PTT, True))
        voice._pressed -= 2.0  # the student held the button for 2 s
        await bench.handle(Event(ev.PTT, False))
        await asyncio.gather(*voice._tasks)

    asyncio.run(go())
    assert states(sent) == ["listening", "transcribing", "speaking", "idle"]
    assert [m["text"] for m in of(sent, "transcript")] == [DIDNT_CATCH]
    assert stt.clips == [] and turns == []


def test_mic_alive_follows_its_callbacks_and_reopen_falls_back_to_the_default(monkeypatch):
    mic = Mic("JBL Endurance Race 2")
    assert not mic.alive()  # never opened
    opened = []

    def fake_open():
        if mic.device is not None:
            raise RuntimeError("device unavailable")
        mic._stream = object()
        mic._last_block = __import__("time").monotonic()
        opened.append(mic.device)

    monkeypatch.setattr(mic, "open", fake_open)
    monkeypatch.setattr(mic, "close", lambda: setattr(mic, "_stream", None))
    mic.reopen()
    assert opened == [None] and mic.device is None and mic.alive()
    mic._last_block -= 5  # no callbacks for 5 s: the device is gone
    assert not mic.alive()
    mic._callback(np.zeros((BLOCK, 1), dtype=np.int16), BLOCK, None, None)
    assert mic.alive()


def test_empty_transcript_says_didnt_catch_that():
    bench, voice, stt, sent, turns = setup("   ")
    asyncio.run(talk(bench, voice))
    assert states(sent) == ["listening", "transcribing", "speaking", "idle"]
    assert [m["text"] for m in of(sent, "transcript")] == [DIDNT_CATCH]
    assert turns == []


def test_stt_failure_says_didnt_catch_that_and_flags_error():
    bench, voice, stt, sent, turns = setup(RuntimeError("503"))
    asyncio.run(talk(bench, voice))
    assert states(sent) == ["listening", "transcribing", "speaking", "idle", "error", "idle"]
    assert of(sent, "state")[-2]["detail"] == "stt: RuntimeError"
    assert [m["text"] for m in of(sent, "transcript")] == [DIDNT_CATCH] and turns == []


def test_stt_failure_puts_voice_down_until_it_hears_again():
    bench, voice, stt, sent, turns = setup(RuntimeError("503"))
    asyncio.run(talk(bench, voice))
    stt.reply = "my LED won't light"
    asyncio.run(talk(bench, voice))
    assert [m["voice"] for m in of(sent, "health")] == ["down", "ok"]
    assert "voice" in of(sent, "health")[0]["fix"]


def test_reset_while_transcribing_drops_the_clip():
    bench, voice, stt, sent, turns = setup("hello", delay=0.05)

    async def reset():
        await asyncio.sleep(0.01)
        await bench.reset()

    asyncio.run(talk(bench, voice, between=reset))
    assert turns == [] and not of(sent, "transcript")
    assert states(sent)[-1] == "idle"


def test_release_after_leaving_listening_stops_recording():
    bench, voice, stt, sent, turns = setup("hello")

    async def go():
        await bench.handle(Event(ev.PTT, True))
        await bench.session.set_state(State.idle)  # e.g. caption-only speech finished meanwhile
        await bench.handle(Event(ev.PTT, False))

    asyncio.run(go())
    assert not voice.mic.recording and stt.clips == [] and not voice._tasks


def test_button_does_nothing_while_bench_is_thinking():
    bench, voice, stt, sent, turns = setup("hello")
    bench.session.state = State.thinking
    asyncio.run(talk(bench, voice))
    assert not of(sent, "state") and stt.clips == []


def test_barge_in_skips_the_preroll():
    bench, voice, stt, sent, turns = setup("hello")

    async def go():
        await bench.handle(Event(ev.PTT, True))
        first = voice.mic.preroll
        await bench.handle(Event(ev.PTT, False))
        await asyncio.gather(*voice._tasks)
        bench.session.state = State.speaking
        await bench.handle(Event(ev.PTT, True))
        return first, voice.mic.preroll

    assert asyncio.run(go()) == (True, False)


def feed(mic, n_blocks, value):
    for _ in range(n_blocks):
        mic._callback(np.full((BLOCK, 1), value, dtype=np.int16), BLOCK, None, None)


def test_mic_keeps_300ms_of_preroll():
    mic = Mic()
    feed(mic, 20, 1)        # 1 s of older audio: only the last 300 ms survives
    mic.start_clip()
    feed(mic, 10, 2)        # 0.5 s while held
    pcm, held = mic.stop_clip()
    assert held == 0.5
    assert len(pcm) == int(0.8 * SAMPLE_RATE)
    assert (pcm[: int(0.3 * SAMPLE_RATE)] == 1).all() and (pcm[int(0.3 * SAMPLE_RATE):] == 2).all()
    feed(mic, 2, 3)         # back to filling the ring, not a clip
    assert mic.stop_clip() == (None, 0.0)
    mic.start_clip(preroll=False)
    feed(mic, 2, 4)
    pcm, held = mic.stop_clip()
    assert len(pcm) == 2 * BLOCK and (pcm == 4).all()


def test_wav_is_16khz_mono_16bit():
    data = wav_bytes(np.arange(1600, dtype=np.int16))
    with wave.open(io.BytesIO(data)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()) == (16000, 1, 2, 1600)
