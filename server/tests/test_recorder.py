"""Session log (#23) and latency marks (#22): recorder.py + metrics.py."""

import asyncio
import json
import logging
import subprocess
import sys

from bench.metrics import load, report, spoken_turns, summarize
from bench.recorder import Recorder
from bench.voice_in import VoiceIn

from .fake_claude import msg, tool
from .test_agent import make
from .test_voice_in import FakeMic, FakeSTT, talk
from .test_voice_out import speaker_for


def recorded(bench, tmp_path):
    rec = Recorder(tmp_path)
    bench.recorder = bench.session.record = rec
    rec.start(bench.session.lab_id)
    return rec


def test_nothing_is_written_until_something_happens(tmp_path):
    agent, _, _ = make()
    rec = recorded(agent.bench, tmp_path)
    assert rec.path is None and not list(tmp_path.iterdir())
    agent.bench.session.record("ptt", down=True)
    lines = [json.loads(x) for x in rec.path.read_text().splitlines()]
    assert [x["kind"] for x in lines] == ["session", "ptt"] and lines[0]["lab"] == "lab1-led"


def test_a_spoken_turn_is_logged_end_to_end_with_its_latency(tmp_path, caplog):
    agent, fake, _ = make(msg(tool("ask_for_probe", probe="Y", at="10c")),
                          msg("Put the yellow probe in row 10. It should read about 1.9 volts."))
    bench = agent.bench
    rec = recorded(bench, tmp_path)
    sp = speaker_for(bench.session)
    bench.speaker, agent.speak, agent.speak_stream = sp, sp.say, sp.speak
    bench.voice = VoiceIn(bench.session, FakeMic(1.0), FakeSTT("my LED won't light"), on_transcript=agent.turn,
                          speak=agent.speak)
    with caplog.at_level(logging.INFO, logger="bench.recorder"):
        asyncio.run(talk(bench, bench.voice))
    recs = load(rec.path)
    kinds = [r["kind"] for r in recs]
    for k in ("ptt", "stt", "turn", "claude", "tool", "expect", "first_text", "first_sentence", "first_audio", "turn_end"):
        assert k in kinds, k
    assert kinds.index("stt") < kinds.index("turn") < kinds.index("first_text") < kinds.index("turn_end")
    (timing,) = spoken_turns(recs)
    assert set(timing) == {"stt", "first_text", "speaking", "first_sentence", "first_audio"}
    assert timing["stt"] <= timing["first_text"] <= timing["first_audio"]
    claude = [r for r in recs if r["kind"] == "claude"]
    assert len(claude) == 2 and all(r["ttft_ms"] is not None and r["ms"] >= r["ttft_ms"] for r in claude)
    assert any("latency: transcript" in m and "first audio" in m for m in caplog.messages)


def test_a_reset_starts_a_new_file_for_the_next_student(tmp_path):
    agent, _, _ = make()
    bench = agent.bench
    rec = recorded(bench, tmp_path)
    bench.session.record("ptt", down=True)
    first = rec.path
    asyncio.run(bench.reset())
    bench.session.record("ptt", down=True)
    assert rec.path != first and len(list(tmp_path.glob("*.jsonl"))) == 2
    assert [r["kind"] for r in load(first)] == ["session", "ptt"]  # nothing from the next student leaks back


def test_probe_events_are_logged(tmp_path):
    from .test_monitor import Rig

    rig = Rig(scenario="led_reversed")
    rec = recorded(rig.bench, tmp_path)
    rig.ask()
    rig.do("Y 10c")
    rig.run(1.0)
    (m,) = [r for r in load(rec.path) if r["kind"] == "monitor"]
    assert m["text"].startswith("Yellow probe (asked for 10c")


def session_log(tmp_path, name="20261024-140000-lab1-led"):
    recs = [
        {"t": 0.0, "kind": "session", "lab": "lab1-led"},
        {"t": 1.0, "kind": "ptt", "down": False},
        {"t": 1.4, "kind": "stt", "ms": 400},
        {"t": 1.4, "kind": "transcript", "role": "student", "text": "my LED won't light"},
        {"t": 1.5, "kind": "turn", "source": "student"},
        {"t": 2.6, "kind": "first_text"},
        {"t": 2.7, "kind": "tool", "name": "ask_for_probe", "input": {"probe": "Y", "at": "10c"}, "error": None},
        {"t": 2.9, "kind": "state", "value": "speaking"},
        {"t": 3.0, "kind": "first_audio", "ms": 150},
        {"t": 5.0, "kind": "state", "value": "idle"},
        {"t": 9.0, "kind": "turn", "source": "event"},
        {"t": 9.5, "kind": "tool", "name": "record_diagnosis", "error": None,
         "input": {"fault_id": "led_reversed", "hint_level": 2, "resolved": False}},
        {"t": 10.0, "kind": "tool", "name": "ask_for_probe", "input": {}, "error": "bad place"},  # errors don't count
        {"t": 30.0, "kind": "ptt", "down": False},
        {"t": 30.3, "kind": "stt", "ms": 300},
        {"t": 30.3, "kind": "transcript", "role": "student", "text": "flipped it"},
        {"t": 30.4, "kind": "turn", "source": "student"},
        {"t": 31.9, "kind": "first_text"},
        {"t": 32.0, "kind": "state", "value": "speaking"},
        {"t": 32.2, "kind": "first_audio", "ms": 120},
        {"t": 33.0, "kind": "tool", "name": "record_diagnosis", "error": None,
         "input": {"fault_id": "led_reversed", "hint_level": 3, "resolved": True}},
        {"t": 34.0, "kind": "state", "value": "idle"},
        {"t": 40.0, "kind": "ptt", "down": False},  # a tap: no transcript, not a spoken turn
        {"t": 40.1, "kind": "state", "value": "idle"},
    ]
    p = tmp_path / f"{name}.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\n{\"t\": 41, \"kind\"")  # + a line cut off by a crash
    return p


def test_metrics_per_session(tmp_path):
    s = summarize(load(session_log(tmp_path)))
    assert (s["turns"], s["events"], s["probes"], s["max_hint"], s["fault"]) == (3, 1, 1, 3, "led_reversed")
    assert s["fixed_after_s"] == 31.6  # first words at 1.4 s, fix confirmed at 33.0 s
    assert s["spoken"] == [{"stt": 0.4, "first_text": 1.6, "speaking": 1.9, "first_audio": 2.0},
                           {"stt": 0.3, "first_text": 1.9, "speaking": 2.0, "first_audio": 2.2}]


def test_metrics_report_and_cli(tmp_path):
    a = session_log(tmp_path)
    session_log(tmp_path, "20261024-150000-lab1-led")
    text = report(sorted(tmp_path.glob("*.jsonl")))
    assert "| 20261024-140000-lab1-led | lab1-led | 3 (1)" in text
    assert "31.6 s" in text and "2 spoken" not in text and "4 spoken turns" in text
    assert "| first audio " in text and "2.10 / 2.20 / 2.20" in text
    out = subprocess.run([sys.executable, "-m", "bench.metrics", str(a)], capture_output=True, text=True, check=True)
    assert "led_reversed" in out.stdout
