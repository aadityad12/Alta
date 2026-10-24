"""look_at_board (#20): request_frame -> the screen's frame -> a downscaled JPEG in the tool result."""

import asyncio
import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from bench import tools as tools_mod
from bench.agent import Agent
from bench.hub import Bench
from bench.labs import load_labs
from bench.main import LABS_DIR, create_app
from bench.protocol import FrameIn

from .fake_claude import FakeClaude, msg, tool
from .test_pod import Inbox

LABS = load_labs(LABS_DIR)


def image_b64(w, h, fmt="PNG") -> str:
    out = io.BytesIO()
    Image.new("RGB", (w, h), (200, 180, 150)).save(out, fmt)
    return base64.b64encode(out.getvalue()).decode()


def make(*script, frame=None, screen=True):
    """frame: what the fake screen answers each request_frame with (b64 string), or None to stay quiet."""
    bench = Bench(LABS)
    bench.session.lab_id = "lab1-led"
    sent = []

    async def broadcast(m):
        sent.append(m.wire())
        if m.type == "request_frame" and frame is not None:
            reply = FrameIn(type="frame", id=m.id, jpeg_b64=frame, w=0, h=0)
            asyncio.get_running_loop().call_soon(lambda: asyncio.ensure_future(bench._handle_ui(reply, None)))

    bench.hub.broadcast = bench.session.broadcast = broadcast
    if screen:
        bench.hub.clients.add(object())
    fake = FakeClaude(*script)
    return Agent(bench, client=fake), fake, sent


def results(request):
    return [c for c in request["messages"][-1]["content"] if c["type"] == "tool_result"]


def test_a_big_photo_comes_back_as_a_1280px_jpeg():
    agent, fake, sent = make(msg(tool("look_at_board")), msg("The LED is in rows 10 and 13."), frame=image_b64(3000, 2000))
    asyncio.run(agent.turn("which rows is the LED in?"))
    assert [m["type"] for m in sent].count("request_frame") == 1
    (r,) = results(fake.requests[1])
    assert not r.get("is_error")
    text, image = r["content"]
    assert text["type"] == "text" and "1280x853" in text["text"]
    assert image["type"] == "image" and image["source"]["media_type"] == "image/jpeg"
    img = Image.open(io.BytesIO(base64.b64decode(image["source"]["data"])))
    assert img.format == "JPEG" and img.size == (1280, 853)


def test_a_small_jpeg_is_passed_through_untouched():
    small = image_b64(960, 540, "JPEG")
    agent, fake, _ = make(msg(tool("look_at_board")), msg("Got it."), frame=small)
    asyncio.run(agent.turn("look at my board"))
    assert results(fake.requests[1])[0]["content"][1]["source"]["data"] == small


def test_no_answer_within_the_timeout_is_an_error(monkeypatch):
    monkeypatch.setattr(tools_mod, "FRAME_TIMEOUT_S", 0.1)
    agent, fake, _ = make(msg(tool("look_at_board")), msg("Let's measure instead."), frame=None)
    asyncio.run(agent.turn("which rows is the LED in?"))
    (r,) = results(fake.requests[1])
    assert r["is_error"] and "didn't send a photo" in r["content"]
    assert agent.bench.frame_waiters == {}


def test_no_screen_means_no_camera():
    agent, fake, sent = make(msg(tool("look_at_board")), msg("OK."), frame=image_b64(10, 10), screen=False)
    asyncio.run(agent.turn("help"))
    (r,) = results(fake.requests[1])
    assert r["is_error"] and "camera isn't connected" in r["content"]
    assert not [m for m in sent if m["type"] == "request_frame"]


def test_a_broken_photo_is_an_error():
    agent, fake, _ = make(msg(tool("look_at_board")), msg("OK."), frame=base64.b64encode(b"not an image").decode())
    asyncio.run(agent.turn("help"))
    (r,) = results(fake.requests[1])
    assert r["is_error"] and "couldn't be read" in r["content"]


def test_one_look_per_turn():
    agent, fake, sent = make(msg(tool("look_at_board")), msg(tool("look_at_board")), msg("OK."),
                             msg(tool("look_at_board")), msg("OK."), frame=image_b64(100, 100))
    asyncio.run(agent.turn("my LED won't light"))
    assert not results(fake.requests[1])[0].get("is_error")
    second = results(fake.requests[2])[0]
    assert second["is_error"] and "already looked" in second["content"]
    asyncio.run(agent.turn("I moved it"))  # a new turn gets a new look
    assert not results(fake.requests[4])[0].get("is_error")
    assert [m["type"] for m in sent].count("request_frame") == 2


def test_more_looks_when_the_student_asks():
    agent, fake, _ = make(msg(tool("look_at_board")), msg(tool("look_at_board")), msg("OK."), frame=image_b64(100, 100))
    asyncio.run(agent.turn("Can you look at my board?"))
    assert not results(fake.requests[2])[0].get("is_error")


def test_probe_events_get_one_look_too():
    agent, fake, _ = make(msg(tool("look_at_board")), msg(tool("look_at_board")), msg("<silent>"), frame=image_b64(100, 100))
    asyncio.run(agent.turn(event="Yellow probe (asked for 10c) now reads a steady 4986 mV. look"))
    assert not results(fake.requests[1])[0].get("is_error")
    assert results(fake.requests[2])[0]["is_error"]  # an event never counts as the student asking


def test_frames_are_saved_for_debugging(tmp_path):
    agent, fake, _ = make(msg(tool("look_at_board")), msg("OK."), frame=image_b64(100, 100))
    agent.tools.frame_dir = tmp_path / "frames"
    asyncio.run(agent.turn("look"))
    (saved,) = (tmp_path / "frames").glob("*-f1.jpg")
    assert Image.open(saved).format == "JPEG"


def test_end_to_end_over_the_websocket():
    app = create_app(demo_ui=False, labs_dir=LABS_DIR, pod_port="off")
    fake = FakeClaude(msg(tool("look_at_board")), msg("Your LED is in rows 10 and 13."))
    app.state.agent._client = fake
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        inbox = Inbox(ws)
        ws.send_json({"type": "text", "text": "which rows is my LED in?"})
        req = inbox.wait_for(lambda m: m["type"] == "request_frame")
        ws.send_json({"type": "frame", "id": "stale-id", "jpeg_b64": image_b64(10, 10), "w": 10, "h": 10})  # ignored
        ws.send_json({"type": "frame", "id": req["id"], "jpeg_b64": image_b64(1920, 1080, "JPEG"), "w": 1920, "h": 1080})
        said = inbox.wait_for(lambda m: m["type"] == "transcript" and m["role"] == "bench" and m["final"], timeout=3)
    assert said["text"] == "Your LED is in rows 10 and 13."
    (r,) = results(fake.requests[1])
    assert "1280x720" in r["content"][0]["text"]
