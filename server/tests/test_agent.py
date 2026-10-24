import asyncio
import json
from types import SimpleNamespace

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
    last = next(m for m in reversed(request["messages"]) if m["role"] == "user" and isinstance(m["content"], list))
    return [c for c in last["content"] if c["type"] == "tool_result"]


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

def test_request_uses_documented_settings(monkeypatch):
    monkeypatch.delenv("BENCH_MODEL", raising=False)  # not whatever the local .env says
    monkeypatch.delenv("BENCH_SPEED", raising=False)
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
    assert OUT_OF_ROUNDS not in [m["content"] for r in fake.requests[:-1] for m in r["messages"] if m["role"] == "system"]
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


def test_speak_first_round_ends_the_turn_without_a_second_request():
    agent, fake, _ = make(msg("Put the yellow probe in row 10.", tool("ask_for_probe", probe="Y", at="10c"),
                              tool("record_diagnosis", fault_id="unknown", confidence=0.3, evidence="-",
                                   hint_level=1, resolved=False)))
    assert run(agent.turn("dark LED")) == "Put the yellow probe in row 10."
    assert len(fake.requests) == 1
    last = agent.messages[-1]  # the results wait for the next message
    assert last["role"] == "user" and [c["type"] for c in last["content"]] == ["tool_result", "tool_result"]
    assert agent.bench.session.expects["Y"].at == "10c"  # the tools still ran


def test_the_next_message_joins_the_unsent_tool_results():
    agent, fake, _ = make(msg("Put the yellow probe in row 10.", tool("ask_for_probe", probe="Y", at="10c")),
                          msg("Good, that's the reading we need."))
    run(agent.turn("dark LED"))
    run(agent.turn(event="Yellow probe now reads a steady 4986 mV."))
    sent = fake.requests[1]["messages"]
    assert [m["role"] for m in sent] == ["user", "assistant", "user"]  # never two user messages in a row
    assert [c["type"] for c in sent[-1]["content"]] == ["tool_result", "text"]
    assert sent[-1]["content"][-1]["text"] == "[event] Yellow probe now reads a steady 4986 mV."
    assert_history_valid(agent.messages)


def test_a_failed_turn_after_a_speak_first_turn_rolls_back_cleanly():
    agent, fake, _ = make(msg("Put the yellow probe in row 10.", tool("ask_for_probe", probe="Y", at="10c")),
                          RuntimeError("network"), msg("Okay."))
    run(agent.turn("dark LED"))
    assert run(agent.turn("what now?")) == GLITCH_LINE
    assert [c["type"] for c in agent.messages[-1]["content"]] == ["tool_result"]  # the text came back out
    run(agent.turn("what now?"))
    assert [c["type"] for c in fake.requests[2]["messages"][-1]["content"]] == ["tool_result", "text"]


def test_spoken_text_before_read_probes_gets_a_second_round_that_knows_what_was_said():
    agent, fake, _ = make(msg("Let me check the probes.", tool("read_probes")),
                          msg("Row 10 reads 5 volts."), probes=[4990, -1, -1, -1])
    assert run(agent.turn("what does it read?")) == "Let me check the probes. Row 10 reads 5 volts."
    note = fake.requests[1]["messages"][-1]
    assert note["role"] == "system" and "Let me check the probes." in note["content"]


def test_a_silent_side_effect_round_is_told_the_student_heard_nothing():
    agent, fake, _ = make(msg(tool("record_diagnosis", fault_id="unknown", confidence=0.3, evidence="-",
                                   hint_level=1, resolved=False)), msg("What does row 10 read?"))
    assert run(agent.turn("help")) == "What does row 10 read?"
    note = fake.requests[1]["messages"][-1]
    assert note["role"] == "system" and "hasn't heard anything" in note["content"]


def test_a_tool_error_in_a_speak_first_round_gets_another_round():
    agent, fake, _ = make(msg("Look at row 10.", tool("highlight", items=[], mode="replace")),
                          msg("<silent>"))
    assert run(agent.turn("help")) == "Look at row 10."
    assert len(fake.requests) == 2 and fake.requests[1]["messages"][-2]["content"][0]["is_error"] is True


def test_prewarm_sends_the_cached_prefix_with_max_tokens_zero():
    agent, fake, _ = make()
    calls = []

    async def create(**kw):
        calls.append(kw)
        return SimpleNamespace(usage=SimpleNamespace(cache_creation_input_tokens=7000, cache_read_input_tokens=0))

    fake.create = create
    run(agent.prewarm())
    kw = calls[0]
    assert kw["max_tokens"] == 0 and "cache_control" not in kw  # breakpoint on the system prompt, not the placeholder
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"} and kw["tools"] == TOOLS
    assert kw["thinking"] == {"type": "adaptive"} and kw["output_config"] == {"effort": "low"}


def test_text_from_an_earlier_round_is_used_if_the_last_round_has_none():
    agent, _, _ = make(msg("Put the yellow probe in row 6.", tool("ask_for_probe", probe="Y", at="6c")), msg())
    assert run(agent.turn("hi")) == "Put the yellow probe in row 6."
