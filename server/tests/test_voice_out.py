import asyncio
from types import SimpleNamespace

import pytest

from bench import bus as ev
from bench.bus import Event
from bench.agent import GLITCH_LINE
from bench.protocol import State
from bench.voice_out import SentenceSplitter, Speaker, _aiter, normalize, sentences_of

from .fake_claude import msg, tool
from .test_agent import make, of, states


class FakeContext:
    def __init__(self, conn):
        self.conn, self.pushed, self.cancelled, self.ended = conn, [], False, False
        self.events: asyncio.Queue = asyncio.Queue()

    async def push(self, text):
        self.pushed.append(text)
        await self.events.put(SimpleNamespace(type="chunk", audio=b"\x01\x00" * 240))

    async def no_more_inputs(self):
        self.ended = True
        await self.events.put(SimpleNamespace(type="done"))

    async def cancel(self):
        self.cancelled = True

    async def receive(self):
        while True:
            e = await self.events.get()
            yield e
            if e.type == "done":
                return


class FakeConn:
    def __init__(self):
        self.contexts, self.kwargs = [], []

    def context(self, **kw):
        self.kwargs.append(kw)
        self.contexts.append(FakeContext(self))
        return self.contexts[-1]


class FakePlayer:
    latency = 0.0

    def __init__(self):
        self.written, self.cleared = [], 0

    def write(self, pcm):
        self.written.append(pcm)

    def clear(self):
        self.cleared += 1

    def pending(self):
        return 0


def speaker_for(session, conn=None):
    sp = Speaker(session, FakePlayer(), voice_id="v1", speed=1.1)
    sp._conn = conn or FakeConn()
    return sp


def test_say_captions_each_sentence_speaks_normalized_text_and_ends_idle():
    agent, _, sent = make()
    s = agent.bench.session
    s.state = State.thinking
    sp = speaker_for(s)
    asyncio.run(sp.say("Row 10 reads 1.92 V. Nice work!"))
    ctx = sp._conn.contexts[0]
    assert ctx.pushed == ["Row 10 reads about 1.9 volts. ", "Nice work! "] and ctx.ended
    kw = sp._conn.kwargs[0]
    assert kw["voice"] == {"id": "v1"} and kw["max_buffer_delay_ms"] == 0 and kw["generation_config"] == {"speed": 1.1}
    assert [(m["text"], m["final"]) for m in of(sent, "transcript")] == [
        ("Row 10 reads 1.92 V.", False), ("Row 10 reads 1.92 V. Nice work!", False), ("Row 10 reads 1.92 V. Nice work!", True)]
    assert states(sent) == ["speaking", "idle"]
    assert len(sp.player.written) == 2 and len(sp.timings) == 1


def test_stop_silences_now_and_mutes_the_rest_of_that_turn():
    agent, _, sent = make()
    s = agent.bench.session
    s.state = State.thinking
    sp = speaker_for(s)
    owner = object()

    async def slow():
        yield "First sentence."
        await asyncio.sleep(0.02)
        yield "Second sentence."

    async def go():
        t = asyncio.create_task(sp.speak(slow(), owner=owner, end_idle=False))
        await asyncio.sleep(0.01)
        sp.stop()
        await s.set_state(State.listening)  # what the hub does on barge-in
        said = await t
        again = await sp.speak(_aiter(["More from the same turn."]), owner=owner)
        return said, again

    said, again = asyncio.run(go())
    ctx = sp._conn.contexts[0]
    assert ctx.pushed == ["First sentence. "] and ctx.cancelled and sp.player.cleared >= 1
    assert said == "First sentence." and again == ""
    assert len(sp._conn.contexts) == 1  # the muted turn never opened another context
    assert states(sent) == ["speaking", "listening"]  # the speaker didn't drag it back to idle


def test_no_tts_still_captions_and_moves_state():
    agent, _, sent = make()
    s = agent.bench.session
    s.state = State.thinking

    sp = Speaker(s, FakePlayer(), voice_id="v1")

    async def broken():
        raise ConnectionError("offline")

    sp.connect = broken
    asyncio.run(sp.say("Hello there."))
    assert [m["text"] for m in of(sent, "transcript")] == ["Hello there.", "Hello there."]
    assert states(sent) == ["speaking", "idle"] and sp.player.written == []


def test_does_not_talk_over_a_student_who_is_talking():
    agent, _, sent = make()
    s = agent.bench.session
    s.state = State.listening
    sp = speaker_for(s)
    asyncio.run(sp.say("Late reply."))
    assert sp.player.written == [] and states(sent) == []


# ---------- agent: sentence streaming ----------

def streaming_agent(*script, probes=None):
    agent, fake, sent = make(*script, probes=probes)
    sp = speaker_for(agent.bench.session)
    agent.speak, agent.speak_stream = sp.say, sp.speak
    agent.bench.speaker = sp
    return agent, sp, sent


def pushed(sp):
    return [p for c in sp._conn.contexts for p in c.pushed]


def test_reply_after_tool_results_is_spoken_while_streaming():
    agent, sp, sent = streaming_agent(msg(tool("clear_highlights")), msg("Row 10 reads 5 V. What should it read?"))
    calls = []
    orig = sp.speak

    async def spy(sentences, **kw):
        calls.append(kw)
        return await orig(sentences, **kw)

    agent.speak_stream = spy
    assert asyncio.run(agent.turn("help")) == "Row 10 reads 5 V. What should it read?"
    assert calls and calls[0]["end_idle"] is False  # went through the live path
    assert pushed(sp) == ["Row 10 reads 5 volts. ", "What should it read? "]
    assert states(sent) == ["thinking", "speaking", "idle"]
    assert of(sent, "transcript")[-1] == {"type": "transcript", "role": "bench", "text": "Row 10 reads 5 V. What should it read?", "final": True}


def test_speak_first_text_is_spoken_while_the_tools_run():
    agent, sp, sent = streaming_agent(
        msg("Let's find where the power stops. Put the yellow probe in 10c.", tool("ask_for_probe", probe="Y", at="10c")),
    )
    asyncio.run(agent.turn("my LED is dark"))
    assert pushed(sp) == ["Let's find where the power stops. ", "Put the yellow probe in row 10, column c. "]
    assert states(sent) == ["thinking", "speaking", "idle"]


def test_slow_turn_gets_a_filler_line_first():
    async def slow(kwargs):
        await asyncio.sleep(0.15)
        return msg("Row 10 reads 5 V.")

    agent, sp, sent = streaming_agent(slow)
    agent.filler_s = 0.05
    asyncio.run(agent.turn("what does it read?"))
    assert pushed(sp) == ["Mm, let me check. ", "Row 10 reads 5 volts. "]
    assert states(sent) == ["thinking", "speaking", "idle"]


def test_no_filler_for_probe_events_or_quick_turns():
    agent, sp, _ = streaming_agent(msg("Quick one."), msg("<silent>"))
    agent.filler_s = 0.05
    asyncio.run(agent.turn("hi"))
    asyncio.run(agent.turn(event="Yellow probe now reads 5 V."))
    assert pushed(sp) == ["Quick one. "]


def test_filler_then_silent_ends_idle():
    async def slow(kwargs):
        await asyncio.sleep(0.15)
        return msg("<silent>")

    agent, sp, sent = streaming_agent(slow)
    agent.filler_s = 0.05
    assert asyncio.run(agent.turn("hm")) is None
    assert states(sent) == ["thinking", "speaking", "idle"]


def test_first_round_reply_without_tools_is_spoken_whole():
    agent, sp, sent = streaming_agent(msg("Good guess. About 2 volts."))
    asyncio.run(agent.turn("2 volts?"))
    assert pushed(sp) == ["Good guess. ", "About 2 volts. "]
    assert states(sent) == ["thinking", "speaking", "idle"]


def test_silent_after_tools_is_never_spoken():
    agent, sp, sent = streaming_agent(msg(tool("read_probes")), msg("<silent>"))
    assert asyncio.run(agent.turn(event="Yellow at 10c changed")) is None
    assert pushed(sp) == [] and not of(sent, "transcript")
    assert states(sent) == ["thinking", "idle"]


def test_barge_in_stops_the_speaker():
    agent, sp, sent = streaming_agent()
    bench = agent.bench
    stopped = []
    sp.stop = lambda: stopped.append(True)

    async def go():
        bench.session.state = State.speaking
        await bench.handle(Event(ev.PTT, True))
        await bench.reset()

    asyncio.run(go())
    assert stopped == [True, True] and states(sent)[0] == "listening"


# ---------- text ----------

@pytest.mark.parametrize("text, said", [
    ("Row 10 reads 1.92 V.", "Row 10 reads about 1.9 volts."),
    ("It's at 4.99V", "It's at about 5 volts"),
    ("about 1.9 V", "about 1.9 volts"),
    ("~5 V", "about 5 volts"),
    ("1892 mV", "about 1.9 volts"),
    ("30 mV", "30 millivolts"),
    ("1 V", "1 volt"),
    ("a 220 Ω resistor, or 10kΩ", "a 220 ohms resistor, or 10 kilohms"),
    ("Put the yellow probe in 10c.", "Put the yellow probe in row 10, column c."),
    ("Try row 13d", "Try row 13, column d"),
    ("anywhere in 10:a-e", "anywhere in row 10"),
    ("the rail:a- rail", "the the minus rail rail"),
    ("yellow on rail:j+", "yellow on the plus rail"),
    ("The LED 💡 is **on**", "The L E D is on"),
    ("Two LEDs", "Two L E Ds"),
])
def test_normalize(text, said):
    assert normalize(text) == said


def test_sentence_splitter_waits_for_the_end_of_a_sentence():
    sp = SentenceSplitter()
    assert sp.feed("Row 10 reads 1.") == []
    assert sp.feed("9 V. Nice") == ["Row 10 reads 1.9 V."]
    assert sp.feed(" work! Is it") == ["Nice work!"]
    assert sp.flush() == ["Is it"]
    assert sentences_of("One. Two? Three") == ["One.", "Two?", "Three"]


def test_a_turn_that_fails_fast_never_says_the_filler():
    agent, sp, sent = streaming_agent(RuntimeError("network"))
    agent.filler_s = 0.2
    assert asyncio.run(agent.turn("hi")) == GLITCH_LINE
    assert "Mm, let me check. " not in pushed(sp)


def test_emotion_goes_into_generation_config():
    agent, _, _ = make()
    s = agent.bench.session
    s.state = State.thinking
    sp = Speaker(s, FakePlayer(), voice_id="v1", emotion="content")
    sp._conn = FakeConn()
    asyncio.run(sp.say("Nice work!"))
    assert sp._conn.kwargs[0]["generation_config"] == {"emotion": "content"}
