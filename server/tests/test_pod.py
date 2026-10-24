import queue
import threading
import time

import pytest
from fastapi.testclient import TestClient

from bench.main import DEMO_LABS_DIR, create_app

from .fake_pod import FakePod


class Inbox:
    """Reads a test WebSocket on a thread so tests can wait with a timeout instead of hanging."""

    def __init__(self, ws) -> None:
        self.ws, self.q = ws, queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        try:
            while True:
                self.q.put(self.ws.receive_json())
        except Exception:
            pass

    def wait_for(self, pred, timeout=2.0):
        end = time.monotonic() + timeout
        while (left := end - time.monotonic()) > 0:
            try:
                m = self.q.get(timeout=left)
            except queue.Empty:
                break
            if pred(m):
                return m
        raise AssertionError(f"timed out after {timeout} s")

    def state(self, value, timeout=2.0):
        return self.wait_for(lambda m: m["type"] == "state" and m["value"] == value, timeout)


def poll(cond, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def pod(tmp_path):
    p = FakePod(str(tmp_path / "pod"))
    yield p
    p.unplug()


def app_for(pod_port):
    return TestClient(create_app(demo_ui=False, labs_dir=DEMO_LABS_DIR, pod_port=pod_port))


def test_samples_reach_the_ui_and_led_follows_state(pod):
    pod.plug()
    with app_for(pod.link) as c, c.websocket_connect("/ws") as ws:
        inbox = Inbox(ws)
        m = inbox.wait_for(lambda m: m["type"] == "probes")
        assert m["mv"] == [5000, 1900, 2, 3] and m["vcc"] == 4987
        assert poll(lambda: c.app.state.pod.connected)

        ws.send_json({"type": "ptt", "down": True})
        inbox.state("listening")
        assert poll(lambda: pod.leds()[-1:] == ["LED LISTEN"])
        ws.send_json({"type": "ptt", "down": False})
        inbox.state("idle")
        assert poll(lambda: pod.leds()[-1:] == ["LED IDLE"])


def test_holding_the_pod_button_starts_listening(pod):
    pod.plug()
    with app_for(pod.link) as c, c.websocket_connect("/ws") as ws:
        inbox = Inbox(ws)
        assert poll(lambda: c.app.state.pod.connected)
        pod.press(True)
        inbox.state("listening")
        assert poll(lambda: pod.leds()[-1:] == ["LED LISTEN"])
        pod.press(False)
        inbox.state("idle")
        assert poll(lambda: pod.leds()[-1:] == ["LED IDLE"])


def test_bad_lines_are_logged_and_skipped(pod):
    pod.plug()
    with app_for(pod.link) as c, c.websocket_connect("/ws") as ws:
        inbox = Inbox(ws)
        assert poll(lambda: c.app.state.pod.connected)
        pod.write_raw(b'garbage\n{"mv":[1]}\n[1,2]\n\xff\xfe\n{"seq":1,"mv":[1,2,3,"x"],"lo":[],"hi":[]}\n')
        pod.mv = [4000, 4000, 4000, 4000]
        inbox.wait_for(lambda m: m["type"] == "probes" and m["mv"] == [4000] * 4)
        assert c.app.state.pod.connected


def test_unplug_and_replug_recovers_within_2s(pod):
    pod.plug()
    with app_for(pod.link) as c, c.websocket_connect("/ws") as ws:
        inbox = Inbox(ws)
        assert poll(lambda: c.app.state.pod.connected)

        pod.unplug()
        m = inbox.state("error", timeout=2.0)
        assert m["detail"] == "pod disconnected"

        n = len(pod.commands)
        pod.plug()
        t0 = time.monotonic()
        inbox.state("idle", timeout=2.0)
        assert time.monotonic() - t0 < 2.0
        inbox.wait_for(lambda m: m["type"] == "probes")
        assert poll(lambda: "LED IDLE" in pod.commands[n:])  # LED back in step with ALTA


def test_a_short_brown_out_is_ridden_out(pod):
    """A real Uno is quiet for ~1 s when it reboots. Reopening the port would reset it a second time."""
    pod.plug()
    with app_for(pod.link) as c, c.websocket_connect("/ws") as ws:
        inbox = Inbox(ws)
        bridge = c.app.state.pod
        assert poll(lambda: bridge.connected)
        pod.paused = True
        time.sleep(1.2)
        assert bridge.connected
        pod.paused = False
        inbox.wait_for(lambda m: m["type"] == "probes")
        with pytest.raises(AssertionError):
            inbox.state("error", timeout=0.3)


def test_only_valid_led_commands_are_replayed(pod):
    pod.plug()
    with app_for(pod.link) as c:
        bridge = c.app.state.pod
        assert poll(lambda: bridge.connected)
        pod.unplug()
        assert poll(lambda: not bridge.connected, timeout=3.0)
        c.portal.call(bridge.send, "LED NOPE")  # after the hub's LED ERROR, so it would be the one replayed
        n = len(pod.commands)
        pod.plug()
        assert poll(lambda: bridge.connected)
        assert poll(lambda: "LED IDLE" in pod.commands[n:])  # replayed, then back to idle with ALTA
        assert "LED NOPE" not in pod.commands[n:]


def test_waits_for_hello_before_sending_commands(pod):
    pod.boot_s = 1.0  # like an Uno rebooting when the port opens
    pod.plug()
    with app_for(pod.link) as c, c.websocket_connect("/ws") as ws:
        inbox = Inbox(ws)
        ws.send_json({"type": "ptt", "down": True})
        inbox.state("listening")
        time.sleep(0.5)
        assert pod.commands == []  # still booting: nothing sent yet, not even PING
        assert poll(lambda: c.app.state.pod.connected, timeout=2.0)
        assert poll(lambda: pod.leds() == ["LED LISTEN"])  # replayed once it said hello


def test_pod_already_running_is_confirmed_with_ping(pod):
    """The default fake pod's hello goes out before the server opens the port, so it's never seen."""
    pod.plug()
    with app_for(pod.link) as c:
        assert poll(lambda: c.app.state.pod.connected, timeout=0.5)
        assert pod.commands[:1] == ["PING"]


def test_pod_that_never_says_hello_or_pong_still_connects(pod):
    pod.hello = pod.answers_ping = False
    pod.plug()
    with app_for(pod.link) as c, c.websocket_connect("/ws") as ws:
        inbox = Inbox(ws)
        inbox.wait_for(lambda m: m["type"] == "probes")  # readings flow right away
        ws.send_json({"type": "ptt", "down": True})
        inbox.state("listening")
        assert not c.app.state.pod.connected
        assert poll(lambda: c.app.state.pod.connected, timeout=4.0)  # 3 s fallback
        assert poll(lambda: pod.leds() == ["LED LISTEN"])


def test_no_pod_is_not_an_error(tmp_path):
    with app_for(str(tmp_path / "nothing-here")) as c, c.websocket_connect("/ws") as ws:
        inbox = Inbox(ws)
        inbox.state("idle")
        ws.send_json({"type": "ptt", "down": True})
        inbox.state("listening")  # on-screen talk button works without a pod
        assert not c.app.state.pod.connected

