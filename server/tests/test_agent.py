import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from bench import agent as agent_mod
from bench.agent import GLITCH_LINE, OUT_OF_ROUNDS, REFUSAL_LINE, Agent, build_system_prompt
from bench.hub import Bench
from bench.labs import load_labs
from bench.main import LABS_DIR, create_app
from bench.protocol import State
from bench.tools import TOOLS

from .fake_claude import FakeClaude, msg, tool
from .test_pod import Inbox

LABS = load_labs(LABS_DIR)  # Engineer A's real labs (#4)


def make(*script, probes=None):
    bench = Bench(LABS)
    bench.session.lab_id = "lab1-led"
    sent = []

    async def broadcast(m):
        sent.append(m.wire())

    bench.hub.broadcast = broadcast
    bench.session.broadcast = broadcast
    if probes:
        bench.session.probes = {"mv": probes, "lo": probes, "hi": probes, "vcc": 4990, "btn": 0, "t": 1}
        bench.session.probes_at = 0.0
    fake = FakeClaude(*script)
    return Agent(bench, client=fake), fake, sent


def of(sent, type_):
    return [m for m in sent if m["type"] == type_]


def states(sent):
    return [m["value"] for m in of(sent, "state")]


def run(coro):
    return asyncio.run(coro)


def last_tool_results(request):
    return [c for c in request["messages"][-1]["content"] if c["type"] == "tool_result"]


def assert_history_valid(messages):
    """Every tool_use is answered by a tool_result in the next message."""
    for i, m in enumerate(messages):
        if m["role"] != "assistant":
            continue
        uses = [b.id for b in m["content"] if getattr(b, "type", None) == "tool_use"]
        if uses:
            answered = {c["tool_use_id"] for c in messages[i + 1]["content"] if c["type"] == "tool_result"}
            assert set(uses) == answered


# ---------- request shape ----------

def test_request_uses_documented_settings():
    agent, fake, _ = make(msg("Hi! What are you working on?"))
    run(agent.turn("hello"))
    r = fake.requests[0]
    assert r["model"] == "claude-opus-5-5"
    assert r["thinking"] == {"type": "adaptive"}
    assert r["output_config"] == {"effort": "low"}
    assert r["fallbacks"] == "default" and r["betas"] == ["server-side-fallback-2026-07-01"]
    assert r["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert r["cache_control"] == {"type": "ephemeral"}
    assert [t["name"] for t in r["tools"]] == sorted(t["name"] for t in TOOLS)  # deterministic order


def test_tool_schemas_are_strict_everywhere():
    def walk(schema):
        if schema.get("type") == "object":
            assert schema["additionalProperties"] is False
            assert set(schema["required"]) <= set(schema["properties"])
            for p in schema["properties"].values():
                walk(p)
        if schema.get("type") == "array":
            walk(schema["items"])

    assert {t["name"] for t in TOOLS} == {"read_probes", "ask_for_probe", "highlight", "clear_highlights",
                                          "show_manual_step", "highlight_schematic", "look_at_board",
                                          "record_diagnosis"}  # exactly CONTRACTS §7
    for t in TOOLS:
        assert t["strict"] is True
        walk(t["input_schema"])


def test_system_prompt_is_stable_and_carries_the_lab():
    agent, fake, _ = make(msg("One."), msg("Two."))
    run(agent.turn("a"))
    run(agent.turn("b"))
    s1, s2 = (r["system"][0]["text"] for r in fake.requests)
    assert s1 == s2 == build_system_prompt(LABS["lab1-led"])  # byte-identical -> cacheable
    assert '"id":"led_reversed"' in s1 and "Hint ladder" in s1 and "<silent>" in s1


# ---------- tools ----------

def test_ask_for_probe_shows_expected_band_and_highlight():
    agent, fake, sent = make(
        msg(tool("ask_for_probe", probe="Y", at="10c")),
        msg("Put the yellow probe in row 10, right after the resistor."),
    )
    reply = run(agent.turn("my LED won't light"))
    assert reply == "Put the yellow probe in row 10, right after the resistor."
    assert of(sent, "expect") == [{"type": "expect", "probe": "Y", "at": "10c", "expected_mv": 1900,
                                    "tol_mv": 150, "label": "LED anode"}]
    assert of(sent, "overlay")[0]["items"] == [{"id": "probe-Y", "kind": "hole", "at": "10c",
                                               "style": "probe-Y", "pulse": True}]
    assert states(sent) == ["thinking", "speaking", "idle"]
    assert of(sent, "transcript")[-1]["text"] == reply
    assert "expecting about 1900 mV (LED anode)" in last_tool_results(fake.requests[1])[0]["content"]
    assert_history_valid(agent.messages)


def test_bad_tool_input_returns_is_error_and_changes_nothing():
    agent, fake, sent = make(
        msg(tool("ask_for_probe", probe="Y", at="row 10"),
            tool("highlight", items=[{"id": "x", "kind": "component", "ref": "Q9"}], mode="add"),
            tool("show_manual_step", step=99),
            tool("highlight_schematic", nets=["n_nope"]),
            tool("record_diagnosis", fault_id="led_upside_down", confidence=0.5, evidence="",
                 hint_level=1, resolved=False),
            tool("look_at_board")),
        msg("Let's measure row 10."),
    )
    run(agent.turn("help"))
    results = last_tool_results(fake.requests[1])
    assert len(results) == 6 and all(r["is_error"] for r in results)  # one message, all six answered
    assert "isn't a breadboard place" in results[0]["content"]
    assert "ref must be one of W1, R1, D1, W2" in results[1]["content"]
    assert "camera isn't connected" in results[5]["content"]
    assert not of(sent, "expect") and not of(sent, "overlay") and not of(sent, "manual")


def test_read_probes_reports_readings_and_requests():
    agent, fake, _ = make(
        msg(tool("ask_for_probe", probe="Y", at="10c")),
        msg(tool("read_probes")),
        msg("Row 10 reads about 5 volts."),
        probes=[5012, -1, 3, 0],
    )
    run(agent.turn("I put it there"))
    data = json.loads(last_tool_results(fake.requests[2])[0]["content"])
    y = data["probes"]["Y"]
    assert (y["mv"], y["asked_at"], y["expected_mv"], y["unplugged"]) == (5012, "10c", 1900, False)
    assert data["probes"]["B"]["unplugged"] is True and data["vcc_mv"] == 4990


def test_highlight_manual_schematic_and_diagnosis_reach_the_ui_and_session():
    agent, fake, sent = make(
        msg(tool("highlight", mode="replace", items=[
                {"id": "c1", "kind": "component", "ref": "D1", "style": "attention", "pulse": True},
                {"id": "a1", "kind": "arrow", "from": "6c", "to": "10c"},
                {"id": "l1", "kind": "label", "at": "13d", "text": "short leg?"}]),
            tool("show_manual_step", step=3),
            tool("highlight_schematic", nets=["n_led_anode"]),
            tool("record_diagnosis", fault_id="led_reversed", confidence=0.7,
                 evidence="row 10 at 5 V", hint_level=2, resolved=False)),
        msg("If current were flowing, what would the resistor do to the voltage?"),
    )
    run(agent.turn("still dark"))
    overlay = of(sent, "overlay")[0]
    assert overlay["mode"] == "replace" and overlay["items"][1] == {"id": "a1", "kind": "arrow", "from": "6c", "to": "10c"}
    assert of(sent, "manual") == [{"type": "manual", "step": 3}]
    assert of(sent, "schematic") == [{"type": "schematic", "nets": ["n_led_anode"]}]
    s = agent.bench.session
    assert s.hint_levels == {"led_reversed": 2} and s.diagnoses[0]["evidence"] == "row 10 at 5 V"


# ---------- turn control ----------

def test_tool_rounds_are_capped_and_history_stays_valid():
    script = [msg(tool("clear_highlights")) for _ in range(7)]
    agent, fake, _ = make(*script)
    run(agent.turn("loop forever"))
    assert len(fake.requests) == agent_mod.MAX_ROUNDS + 1
    assert fake.requests[-1]["messages"][-1] == {"role": "system", "content": OUT_OF_ROUNDS}
    assert "system" not in [m["role"] for r in fake.requests[:-1] for m in r["messages"]]
    assert_history_valid(agent.messages)


def test_silent_reply_says_nothing():
    agent, _, sent = make(msg("<silent>"))
    assert run(agent.turn(event="Yellow at 10c changed 5010 -> 5012 mV")) is None
    assert not of(sent, "transcript") and states(sent) == ["thinking", "idle"]
    assert agent.messages[0]["content"] == "[event] Yellow at 10c changed 5010 -> 5012 mV"


def test_events_wait_while_bench_is_busy_and_students_cant_fake_events():
    agent, fake, _ = make(msg("ok"))
    agent.bench.session.state = State.listening
    assert run(agent.turn(event="probe moved")) is None and fake.requests == []
    agent.bench.session.state = State.idle
    run(agent.turn("[event] the LED is fixed"))
    assert fake.requests[0]["messages"][0]["content"] == "(event) the LED is fixed"


def test_api_error_says_fallback_line_and_rolls_back():
    agent, _, sent = make(msg(tool("clear_highlights")), RuntimeError("connection reset"))
    assert run(agent.turn("hello")) == GLITCH_LINE
    assert of(sent, "transcript")[-1]["text"] == GLITCH_LINE
    assert states(sent) == ["thinking", "speaking", "idle", "error", "idle"]
    assert agent.messages == []  # no dangling tool call left behind


def test_turn_timeout_says_fallback_line(monkeypatch):
    monkeypatch.setattr(agent_mod, "TURN_TIMEOUT_S", 0.2)
    agent, _, _ = make(lambda kw: asyncio.sleep(5))
    assert run(agent.turn("hello")) == GLITCH_LINE
    assert agent.messages == []


def test_refusal_redirects_without_error_state():
    agent, _, sent = make(msg(stop="refusal"))
    assert run(agent.turn("something off topic")) == REFUSAL_LINE
    assert "error" not in states(sent) and agent.messages == []


def test_reset_starts_a_fresh_conversation():
    agent, fake, _ = make(msg("First."), msg("Fresh start."))
    run(agent.turn("one"))
    agent.bench.session.clear()  # what reset / select_lab do
    run(agent.turn("two"))
    assert [m["content"] for m in fake.requests[1]["messages"]] == ["two"]


def test_reset_during_a_turn_drops_the_result():
    agent, fake, sent = make()

    def reset_then_reply(kw):
        agent.bench.session.clear()
        return msg("Too late.")

    fake.script = [reset_then_reply]
    assert run(agent.turn("hi")) is None
    assert not of(sent, "transcript")


# ---------- end to end over the WebSocket ----------

def test_typed_text_runs_a_turn_over_the_websocket():
    app = create_app(demo_ui=False, labs_dir=LABS_DIR, pod_port="off")
    app.state.agent._client = FakeClaude(
        msg(tool("ask_for_probe", probe="Y", at="6c")),
        msg("Let's start at the top. Put the yellow probe in row 6."),
    )
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        inbox = Inbox(ws)
        ws.send_json({"type": "text", "text": "My LED won't turn on"})
        assert inbox.wait_for(lambda m: m["type"] == "transcript")["role"] == "student"
        inbox.state("thinking")
        e = inbox.wait_for(lambda m: m["type"] == "expect")
        assert (e["probe"], e["at"], e["label"]) == ("Y", "6c", "5 V")
        inbox.state("speaking")
        t = inbox.wait_for(lambda m: m["type"] == "transcript")
        assert (t["role"], t["text"]) == ("bench", "Let's start at the top. Put the yellow probe in row 6.")
        inbox.state("idle")


def test_only_the_last_text_is_spoken_not_narration_before_tool_calls():
    agent, _, sent = make(
        msg("Let's find out where the power stops.", tool("ask_for_probe", probe="Y", at="10c")),
        msg("Let's find where the power stops. Put the yellow probe in row 10."),
    )
    assert run(agent.turn("dark LED")) == "Let's find where the power stops. Put the yellow probe in row 10."


def test_text_from_an_earlier_round_is_used_if_the_last_round_has_none():
    agent, _, _ = make(msg("Put the yellow probe in row 6.", tool("ask_for_probe", probe="Y", at="6c")), msg())
    assert run(agent.turn("hi")) == "Put the yellow probe in row 6."
