import asyncio
import socket
from types import SimpleNamespace

import anthropic
import httpx

from bench import preflight as pf
from bench.labs import load_labs
from bench.main import LABS_DIR

from .fake_pod import FakePod

DEMO = {"BENCH_MODEL": "claude-opus-5-5", "BENCH_SPEED": "fast", "ANTHROPIC_API_KEY": "k", "CARTESIA_API_KEY": "k"}


def by_name(checks):
    return {c.name: c for c in checks}


def test_demo_settings_are_ok():
    c = by_name(pf.check_settings(DEMO))
    assert c["model"].status == pf.OK and c["voice"].status == pf.OK
    assert "anthropic" not in c and "cartesia" not in c


def test_dev_model_and_missing_keys_are_flagged():
    c = by_name(pf.check_settings({"BENCH_MODEL": "claude-haiku-5-5", "BENCH_VOICE": "robot"}))
    assert c["model"].status == pf.WARN and "BENCH_SPEED=fast" in c["model"].fix
    assert c["voice"].status == pf.WARN
    assert c["anthropic"].status == pf.BAD and c["cartesia"].status == pf.BAD


def test_pod_ok_shows_the_readings(tmp_path):
    pod = FakePod(str(tmp_path / "pod"), mv=(5000, 1900, -1, 3))
    pod.boot_s = 0.3  # an Uno resets when the port opens, then says hello
    pod.plug()
    try:
        c = pf.check_pod(pod.link, wait_s=2)
    finally:
        pod.unplug()
    assert c.status == pf.OK
    assert "fw 0.1.0" in c.detail and "Y 5.00 V" in c.detail and "G unplugged" in c.detail


def test_pod_already_running_answers_ping(tmp_path):
    pod = FakePod(str(tmp_path / "pod"))
    pod.hello = False
    pod.plug()
    try:
        c = pf.check_pod(pod.link, wait_s=2)
    finally:
        pod.unplug()
    assert c.status == pf.OK and "fw 0.1.0" in c.detail and "PING" in pod.commands


def test_pod_missing_or_silent(tmp_path):
    assert pf.check_pod(str(tmp_path / "nothing")).status == pf.BAD
    pod = FakePod(str(tmp_path / "pod"))
    pod.hello, pod.paused = False, True
    pod.plug()
    try:
        c = pf.check_pod(pod.link, wait_s=0.5)
    finally:
        pod.unplug()
    assert c.status == pf.BAD and "no readings" in c.detail


class FakeCreate:
    def __init__(self, result):
        self.result = result
        self.beta = self
        self.messages = self
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def test_claude_prewarms_with_the_demo_settings(monkeypatch):
    monkeypatch.setenv("BENCH_MODEL", "claude-opus-5-5")
    monkeypatch.setenv("BENCH_SPEED", "fast")
    lab = load_labs(LABS_DIR)[pf.DEMO_LAB]
    usage = SimpleNamespace(cache_creation_input_tokens=7000, cache_read_input_tokens=0)
    client = FakeCreate(SimpleNamespace(usage=usage))
    c = asyncio.run(pf.check_claude(lab, client))
    assert c.status == pf.OK
    assert client.kwargs["model"] == "claude-opus-5-5" and client.kwargs["speed"] == "fast"
    assert client.kwargs["max_tokens"] == 0


def test_claude_wrong_key():
    lab = load_labs(LABS_DIR)[pf.DEMO_LAB]
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.AuthenticationError("bad key", response=httpx.Response(401, request=req), body=None)
    c = asyncio.run(pf.check_claude(lab, FakeCreate(err)))
    assert c.status == pf.BAD and "ANTHROPIC_API_KEY" in c.fix


def test_stt_failure_points_at_typing():
    class Broken:
        model = "ink-whisper"

        async def __call__(self, wav):
            raise ConnectionError("offline")

    c = asyncio.run(pf.check_stt(Broken()))
    assert c.status == pf.BAD and "type" in c.fix


def test_ports_in_use():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        assert pf.check_ports((port,)).status == pf.WARN
    assert pf.check_ports((port,)).status == pf.OK
