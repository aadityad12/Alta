"""Probe monitor (#21), driven by the mock pod's own voltage model (#9) in simulated time.

`Bench` scripts the mock the way a student would (plug a probe, bounce it, stage a fault, fix it) and
feeds every 50 ms sample to the monitor, so the sequences are what the mock really sends, minus the pty.
"""

import asyncio
import importlib.util
import os
from pathlib import Path

import pytest

from bench import bus as ev
from bench.agent import Agent
from bench.hub import Bench
from bench.labs import load_labs
from bench.main import LABS_DIR
from bench.monitor import MAX_AGE_S, Monitor
from bench.protocol import PROBES, ExpectOut, State

from .fake_claude import FakeClaude, msg, tool

_spec = importlib.util.spec_from_file_location("mock_pod", Path(__file__).resolve().parents[1] / "tools" / "mock_pod.py")
mock_pod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mock_pod)

LABS = load_labs(LABS_DIR)
TICK = mock_pod.TICK_S


class Rig:
    """The mock pod's model + the monitor, on a fake clock."""

    def __init__(self, lab="lab1-led", scenario="normal", seed=1) -> None:
        self.bench = Bench(LABS)
        self.bench.session.lab_id = lab
        self.sent = []

        async def broadcast(m):
            self.sent.append(m.wire())

        self.bench.hub.broadcast = self.bench.session.broadcast = broadcast
        self.pod = mock_pod.MockPod(LABS_DIR, None, seed)
        os.close(self.pod.master)
        os.close(self.pod.slave)
        self.pod.load_lab(lab, scenario)
        self.pod.command("unplug all")
        self.t = 0.0
        self.monitor = Monitor(self.bench, clock=lambda: self.t)
        self.events = self.bench.bus.subscribe()
        self.heard: list[tuple[float, str]] = []

    def do(self, *cmds: str) -> "Rig":
        for c in cmds:
            self.pod.command(c)
        return self

    def run(self, seconds: float) -> list[str]:
        """Feed `seconds` of samples; returns the MONITOR messages published meanwhile."""
        out = []
        for _ in range(round(seconds / TICK)):
            self.t += TICK
            r = [self.pod.reading(p, mock_pod.VCC_MV) for p in PROBES]
            self.monitor.on_sample({"mv": [x[0] for x in r], "lo": [x[1] for x in r], "hi": [x[2] for x in r],
                                    "vcc": mock_pod.VCC_MV, "btn": 0})
            while not self.events.empty():
                e = self.events.get_nowait()
                if e.kind == ev.MONITOR:
                    out.append(e.data)
                    self.heard.append((self.t, e.data))
        return out

    def bounce(self, probe: str, hole: str, seconds: float) -> list[str]:
        """Contact bounce while plugging: in, out, in, out... every sample."""
        out = []
        for i in range(round(seconds / TICK)):
            self.do(f"{probe} {hole}" if i % 2 == 0 else f"unplug {probe}")
            out += self.run(TICK)
        return out

    def ask(self, probe="Y", at="10c", net="n_led_anode") -> None:
        n = next(x for x in LABS[self.bench.session.lab_id].data["nets"] if x["id"] == net)
        e = ExpectOut(probe=probe, at=at, expected_mv=n["expected_mv"], tol_mv=n["tol_mv"], label=n["label"])
        asyncio.run(self.bench.session.expect(e))

    def state(self, value: State) -> None:
        self.bench.session.state = value


# ---------- plug, bounce, steady, fix ----------

def test_plugging_the_asked_probe_is_reported_once_it_holds_still():
    rig = Rig(scenario="led_reversed")
    rig.ask()
    assert rig.run(2.0) == []  # floating on the desk: never steady
    rig.do("Y 10c")
    got = rig.run(3.0)
    assert len(got) == 1
    assert got[0].startswith("Yellow probe (asked for 10c, LED anode) now reads a steady 49")
    assert "outside the expected range" in got[0]
    assert rig.heard[0][0] - 2.0 <= 0.6  # 500 ms of steady + one sample


def test_contact_bounce_is_never_reported():
    rig = Rig()
    rig.ask()
    rig.run(1.0)
    assert rig.bounce("Y", "10c", 0.6) == []
    rig.do("Y 10c")
    got = rig.run(3.0)
    assert len(got) == 1 and "in the expected range" in got[0]


def test_unplugged_reading_minus_one_is_never_steady():
    rig = Rig()
    rig.ask()
    rig.do("unplug Y -1")
    assert rig.run(2.0) == []


def test_steady_probe_is_reported_once_not_again():
    rig = Rig()
    rig.ask()
    rig.do("Y 10c")
    assert len(rig.run(1.0)) == 1
    assert rig.run(10.0) == []


def test_fixing_the_fault_is_confirmed_automatically():
    rig = Rig(scenario="led_reversed")
    rig.ask()
    rig.do("Y 10c")
    rig.run(1.5)
    rig.do("fix")
    got = rig.run(2.0)
    assert len(got) == 1
    assert "is now in the expected range: a steady 18" in got[0] or "is now in the expected range: a steady 19" in got[0]
    assert "It read 49" in got[0]
    assert rig.monitor.detectors["Y"].last_in_band is True


def test_fix_via_the_dim_resistor_crosses_the_band():
    rig = Rig(scenario="wrong_resistor_10k")  # 1650 mV, just under 1900 ± 150
    rig.ask()
    rig.do("Y 10c")
    assert "outside the expected range" in rig.run(1.0)[0]
    rig.do("fix")
    got = rig.run(1.5)
    assert len(got) == 1 and "is now in the expected range" in got[0]


def test_a_jiggle_that_comes_back_is_not_news():
    rig = Rig()
    rig.ask()
    rig.do("Y 10c")
    rig.run(1.0)
    rig.do("unplug Y")
    rig.run(0.3)  # long enough to look moved
    rig.do("Y 10c")
    assert rig.run(2.0) == []


def test_moving_between_holes_at_the_same_voltage_still_answers_the_request():
    rig = Rig()
    rig.do("Y rail:a+")
    rig.run(1.0)
    rig.ask(at="6c", net="n_5v")  # the probe already reads 5 V, so only the move tells us
    assert rig.run(1.0) == []  # ALTA says where to put it
    rig.do("unplug Y")
    rig.run(0.4)
    rig.do("Y 6c")
    got = rig.run(1.5)
    assert len(got) == 1 and "in the expected range" in got[0]


def test_already_in_place_when_asked_is_not_reported():
    rig = Rig()
    rig.do("Y 10c")
    rig.run(1.0)
    rig.ask()
    assert rig.run(3.0) == []


def test_a_humming_wire_is_not_steady():
    """A loose wire can average out steady while each 50 ms window swings with mains hum."""
    rig = Rig()
    rig.ask()
    for _ in range(60):
        rig.t += TICK
        rig.monitor.on_sample({"mv": [2500, -1, -1, -1], "lo": [2200, -1, -1, -1], "hi": [2800, -1, -1, -1]})
    assert rig.monitor.pending == {} and rig.events.empty()


def test_probes_nobody_asked_for_are_ignored():
    rig = Rig()
    rig.ask(probe="Y")
    rig.do("B 10c", "G rail:a+")
    assert rig.run(2.0) == []


def test_hovering_at_the_band_edge_does_not_flap():
    rig = Rig()
    rig.ask()
    for i in range(400):  # 20 s around 1750, the band's lower edge, wandering ±12 mV
        rig.t += TICK
        v = 1750 + (12 if (i // 37) % 2 else -12)
        rig.monitor.on_sample({"mv": [v, -1, -1, -1], "lo": [v - 5, -1, -1, -1], "hi": [v + 5, -1, -1, -1]})
    got = []
    while not rig.events.empty():
        got += [e.data] if (e := rig.events.get_nowait()).kind == ev.MONITOR else []
    assert len(got) == 1


def test_a_new_request_starts_over():
    rig = Rig()
    rig.ask()
    rig.do("Y 10c")
    rig.run(1.0)
    rig.ask(at="13c", net="n_led_cathode")
    rig.run(1.0)
    rig.do("unplug Y")
    rig.run(0.4)
    rig.do("Y 13c")
    got = rig.run(1.5)
    assert len(got) == 1 and got[0].startswith("Yellow probe (asked for 13c, LED cathode) now reads a steady")


def test_lab2_covering_the_sensor_is_reported():
    rig = Rig(lab="lab2-light")
    rig.ask(at="30c", net="n_out")
    rig.do("Y 30c")
    assert "in the expected range" in rig.run(1.0)[0]  # room light, ~3.6 V
    rig.do("light 0")  # cover the sensor
    got = rig.run(1.5)
    assert len(got) == 1 and "outside the expected range" in got[0]


# ---------- never interrupt ----------

def test_events_wait_while_anyone_is_talking():
    rig = Rig()
    rig.ask()
    rig.do("Y 10c")
    for busy in (State.listening, State.transcribing, State.thinking, State.speaking, State.error):
        rig.state(busy)
        assert rig.run(1.5) == []
    rig.state(State.idle)
    got = rig.run(TICK)
    assert len(got) == 1 and "in the expected range" in got[0]


def test_two_probes_go_out_as_one_message():
    rig = Rig(scenario="led_reversed")
    rig.ask(probe="Y")
    rig.ask(probe="B", at="13c", net="n_led_cathode")
    rig.state(State.speaking)
    rig.do("Y 10c", "B 13c")
    rig.run(1.5)
    rig.state(State.idle)
    got = rig.run(TICK)
    assert len(got) == 1 and got[0].count("probe (asked for") == 2


def test_stale_events_are_dropped():
    rig = Rig()
    rig.ask()
    rig.state(State.listening)
    rig.do("Y 10c")
    rig.run(1.0 + MAX_AGE_S)
    rig.state(State.idle)
    assert rig.run(1.0) == []


def test_reset_forgets_everything():
    rig = Rig()
    rig.ask()
    rig.state(State.speaking)
    rig.do("Y 10c")
    rig.run(1.0)
    rig.bench.session.clear()
    rig.state(State.idle)
    assert rig.run(2.0) == []
    assert rig.monitor.detectors == {}


def test_a_waiting_event_for_a_cleared_request_is_dropped():
    rig = Rig()
    rig.ask()
    rig.state(State.speaking)
    rig.do("Y 10c")
    rig.run(1.0)
    asyncio.run(rig.bench.session.expect(ExpectOut(probe="Y", clear=True)))
    rig.state(State.idle)
    assert rig.run(1.0) == []


def test_cleared_request_stops_watching():
    rig = Rig()
    rig.ask()
    rig.run(0.5)
    asyncio.run(rig.bench.session.expect(ExpectOut(probe="Y", clear=True)))
    rig.do("Y 10c")
    assert rig.run(2.0) == []


# ---------- end to end with the agent ----------

def test_agent_reacts_to_the_probe_with_no_button_press_and_only_once():
    async def main():
        rig = Rig(scenario="led_reversed")
        fake = FakeClaude(
            msg(tool("ask_for_probe", probe="Y", at="10c")),
            msg("Put the yellow probe in row 10."),
            msg("Row 10 reads the full 5 volts. What would the resistor do if current were flowing?"),
            msg("<silent>"),
        )
        agent = Agent(rig.bench, client=fake)
        task = asyncio.create_task(agent.run())
        await asyncio.sleep(0)
        await agent.turn("my LED won't light")
        assert rig.bench.session.expects["Y"].at == "10c"
        rig.do("Y 10c")
        for _ in range(60):  # 3 s of samples, letting the agent run between them
            rig.run(TICK)
            await asyncio.sleep(0.01)
        task.cancel()
        return fake, rig

    fake, rig = asyncio.run(main())
    assert len(fake.requests) == 3  # the student's turn (2 rounds) + exactly one probe reaction
    last_user = fake.requests[2]["messages"][-1]["content"]
    assert last_user.startswith("[event] Yellow probe (asked for 10c, LED anode) now reads a steady 49")
    said = [m["text"] for m in rig.sent if m["type"] == "transcript" and m["role"] == "bench"]
    assert said[-1].startswith("Row 10 reads the full 5 volts")


@pytest.mark.parametrize("seed", range(5))
def test_no_double_reactions_in_five_tries(seed):
    """#21 Done when: plug, wait, fix, wait, with different noise each time → exactly two events."""
    rig = Rig(scenario="led_reversed", seed=seed)
    rig.ask()
    rig.run(1.0)
    rig.bounce("Y", "10c", 0.4)
    rig.do("Y 10c")
    rig.run(3.0)
    rig.do("unplug Y")  # bumped while fixing the LED
    rig.run(0.1)
    rig.do("Y 10c")
    rig.run(1.0)
    rig.do("fix")
    rig.run(3.0)
    kinds = ["fixed" if "is now in the expected range" in t else "reading" for _, t in rig.heard]
    assert kinds == ["reading", "fixed"]
