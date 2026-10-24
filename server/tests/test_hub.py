import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bench.main import DEMO_LABS_DIR, create_app
from bench.protocol import ExpectOut, OverlayItem, State
from bench.session import Session, can_transition


def recv_until(ws, type_, limit=200):
    """Read messages until one of `type_` arrives; return (it, everything read before it)."""
    seen = []
    for _ in range(limit):
        m = ws.receive_json()
        if m["type"] == type_:
            return m, seen
        seen.append(m)
    raise AssertionError(f"no {type_!r} in {[m['type'] for m in seen]}")


@pytest.fixture
def client():
    """Normal mode, with the bundled demo lab standing in for labs/."""
    with TestClient(create_app(demo_ui=False, labs_dir=DEMO_LABS_DIR)) as c:
        yield c


@pytest.fixture
def demo_client(tmp_path):
    with TestClient(create_app(demo_ui=True, labs_dir=tmp_path)) as c:
        yield c


def test_connect_sends_lab_state_and_step(client):
    with client.websocket_connect("/ws") as ws:
        lab = ws.receive_json()
        assert lab["type"] == "lab"
        assert lab["lab"]["id"] == "lab1-led"
        assert "# Lab 1" in lab["lab"]["manual_md"]
        assert lab["lab"]["schematic_url"] == "/labs/lab1-led/schematic.svg"
        assert ws.receive_json() == {"type": "state", "value": "idle"}
        assert ws.receive_json() == {"type": "manual", "step": 1}


def test_no_labs_is_an_error_not_a_crash(tmp_path):
    with TestClient(create_app(demo_ui=False, labs_dir=tmp_path)) as c, c.websocket_connect("/ws") as ws:
        assert ws.receive_json() == {"type": "error", "message": "no labs found in labs/"}
        assert c.get("/health").json() == {"ok": True}


def test_demo_ui_streams_lab_and_probes(demo_client):
    with demo_client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "lab"
        probes, _ = recv_until(ws, "probes")
        assert len(probes["mv"]) == len(probes["lo"]) == len(probes["hi"]) == 4
        assert {"vcc", "btn", "t"} <= probes.keys()


def test_probes_are_throttled_to_10hz(demo_client):
    """The fake pod sends 20 Hz; the UI should get about 10 Hz."""
    with demo_client.websocket_connect("/ws") as ws:
        recv_until(ws, "probes")
        n, start = 0, time.monotonic()
        while time.monotonic() - start < 2.0:
            if ws.receive_json()["type"] == "probes":
                n += 1
        assert 15 <= n <= 22, n


def test_unknown_and_malformed_messages_get_polite_errors(client):
    with client.websocket_connect("/ws") as ws:
        recv_until(ws, "manual")
        ws.send_json({"type": "dance"})
        assert ws.receive_json() == {"type": "error", "message": "unknown message type: 'dance'"}
        ws.send_json({"type": "ptt"})
        assert ws.receive_json()["message"].startswith("bad 'ptt' message: down")
        ws.send_text("not json")
        assert ws.receive_json() == {"type": "error", "message": "expected a JSON object"}
        ws.send_json({"type": "select_lab", "lab_id": "nope"})
        assert ws.receive_json() == {"type": "error", "message": "unknown lab: nope"}
        # still connected and working
        ws.send_json({"type": "select_lab", "lab_id": "lab1-led"})
        assert ws.receive_json()["type"] == "lab"


def test_reset_clears_session_and_tells_every_client(client):
    bench = client.app.state.bench
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        recv_until(a, "manual")
        recv_until(b, "manual")
        s = bench.session
        client.portal.call(s.expect, ExpectOut(probe="Y", at="10c", expected_mv=1900, tol_mv=300, label="LED anode"))
        client.portal.call(s.set_state, State.thinking)
        a.send_json({"type": "step", "step": 3})
        s.hint_levels["led_reversed"] = 2
        for ws in (a, b):
            recv_until(ws, "state")

        a.send_json({"type": "reset"})
        for ws in (a, b):
            got = [ws.receive_json() for _ in range(5)]
            assert [m["type"] for m in got] == ["lab", "overlay_clear", "expect", "manual", "state"]
            assert got[2] == {"type": "expect", "probe": "Y", "clear": True}
            assert got[3]["step"] == 1
            assert got[4]["value"] == "idle"
        assert (s.step, s.expects, s.hint_levels, s.transcript, s.state) == (1, {}, {}, [], State.idle)


def test_lab_files_are_served_without_path_traversal(client):
    r = client.get("/labs/lab1-led/schematic.svg")
    assert r.status_code == 200 and 'id="n_led_anode"' in r.text
    assert client.get("/labs").json() == [{"id": "lab1-led", "title": "Lab 1 · Light an LED"}]
    assert client.get("/labs/lab1-led/..%2F..%2Fmain.py").status_code == 404
    assert client.get("/labs/nope/lab.yaml").status_code == 404


def test_state_machine_and_led_commands():
    sent, cmds = [], []

    async def broadcast(m):
        sent.append(m.wire())

    async def pod(c):
        cmds.append(c)

    import asyncio

    s = Session(broadcast=broadcast, pod_command=pod)

    async def run():
        for st in ["listening", "transcribing", "thinking", "speaking", "idle"]:
            assert await s.set_state(State(st))
        assert not await s.set_state(State.speaking)  # idle -> speaking is not a thing
        assert await s.set_state(State.error, "pod unplugged")

    asyncio.run(run())
    assert cmds == ["LED LISTEN", "LED THINK", "LED THINK", "LED SPEAK", "LED IDLE", "LED ERROR"]
    assert sent[-1] == {"type": "state", "value": "error", "detail": "pod unplugged"}
    assert can_transition(State.speaking, State.listening)  # barge-in
    assert can_transition(State.idle, State.thinking)  # typed question / probe event


def test_overlay_item_uses_contract_field_names():
    item = OverlayItem(id="a1", kind="arrow", from_="6c", to="10c", style="attention")
    assert item.wire() == {"id": "a1", "kind": "arrow", "from": "6c", "to": "10c", "style": "attention"}
    assert OverlayItem.model_validate({"id": "a1", "kind": "arrow", "from": "6c", "to": "10c"}).from_ == "6c"
