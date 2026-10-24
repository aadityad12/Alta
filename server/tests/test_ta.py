"""TA dashboard (#24): station status from session records, the live tee, and the replayed room."""

import asyncio

from fastapi.testclient import TestClient

from bench import ta
from bench.labs import load_labs
from bench.main import LABS_DIR, create_app

from .fake_claude import msg, tool
from .test_agent import make

LABS = load_labs(LABS_DIR)


def diag(fault, hint, resolved=False):
    return {"kind": "tool", "name": "record_diagnosis",
            "input": {"fault_id": fault, "hint_level": hint, "confidence": 0.9, "resolved": resolved}}


def test_a_station_gets_stuck_diagnosed_and_fixed():
    v = ta.StationView("lab1-led")
    assert v.status(0) == "building"
    v.feed(10, {"kind": "turn", "source": "student"})
    v.feed(12, {"kind": "turn", "source": "event"})  # probe events don't restart the clock
    v.feed(20, diag("unknown", 1))
    v.feed(40, diag("led_reversed", 2))
    card = v.card(70, LABS, "Station 1", live=True)
    assert (card["status"], card["stuck_s"], card["fault_name"], card["hint"]) == ("stuck", 60, "LED in backwards", 2)
    v.feed(80, diag("led_reversed", 2, resolved=True))
    assert v.status(81) == "fixed" and v.fixed["led_reversed"] == 1
    assert v.status(80 + ta.CALM_AFTER_S + 1) == "building"


def test_the_live_station_follows_a_real_agent_turn_and_resets():
    agent, _, _ = make(msg("Put the yellow probe in row 10.", tool("record_diagnosis", fault_id="led_reversed",
                                                                         confidence=0.6, evidence="dark LED",
                                                                         hint_level=1, resolved=False)), msg("ok"))
    room = ta.Room(agent.bench, samples=[])
    asyncio.run(agent.turn("my LED won't light"))
    live = room.snapshot()["stations"][0]
    assert (live["live"], live["status"], live["fault"], live["hint"]) == (True, "stuck", "led_reversed", 1)
    asyncio.run(agent.bench.reset())  # new student
    assert room.snapshot()["stations"][0]["status"] == "building"


def test_replayed_stations_are_a_function_of_time_and_fill_the_chart():
    room = ta.Room(make()[0].bench)
    assert len(room.snapshot()["stations"]) == 6
    room.t0 = room.clock() - 3600
    a, b = room.snapshot(), room.snapshot()
    assert a == b  # same moment, same room
    assert {c["status"] for c in a["stations"][1:]} <= {"building", "stuck", "fixed"}
    counts = {f["id"]: f["count"] for f in a["faults"]}
    assert counts["led_reversed"] == max(counts.values())  # the most common fault in the room


def test_ta_page_and_json():
    with TestClient(create_app(demo_ui=False, pod_port="off")) as c:
        assert "TA view" in c.get("/ta").text
        d = c.get("/ta/stations").json()
        assert d["stations"][0]["name"] == "Station 1" and d["faults"]


def test_samples_carry_no_words():
    for recs in ta.load_samples():
        for r in recs:
            assert not {"text", "evidence", "reply"} & r.keys() and not {"evidence"} & (r.get("input") or {}).keys()
