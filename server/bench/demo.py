"""--demo-ui mode: no pod, no keys. Fakes probes and a looping TA conversation so the UI can be built (#30)."""

import asyncio
import math
import random

from . import bus as ev
from .bus import Event
from .hub import Bench
from .protocol import (
    ExpectOut,
    ManualOut,
    OverlayClearOut,
    OverlayItem,
    OverlayOut,
    SchematicOut,
    State,
)

SAMPLE_HZ = 20  # same rate as the real pod (CONTRACTS §2)


async def run_demo(bench: Bench) -> None:
    await asyncio.gather(fake_pod(bench), demo_script(bench))


async def fake_pod(bench: Bench) -> None:
    """Pod sample lines at 20 Hz through the bus, so the real 10 Hz throttle is exercised.

    Y sits on 5 V, B on the LED anode (reads 5 V: the LED is in backwards), G on ground,
    W slowly sweeps 0-5 V. The talk button is "held" for a moment every 10 s.
    """
    seq = 0
    while True:
        t = seq * 1000 // SAMPLE_HZ
        sweep = int(2500 + 2500 * math.sin(t / 2000))
        base = [5000, 4990, 2, sweep]
        mv = [v + random.randint(-12, 12) if v > 20 else v for v in base]
        bench.bus.publish(Event(ev.POD_SAMPLE, {
            "seq": seq,
            "t": t,
            "mv": mv,
            "lo": [max(0, v - random.randint(5, 25)) for v in mv],
            "hi": [v + random.randint(5, 25) for v in mv],
            "vcc": 4987 + random.randint(-5, 5),
            "btn": int(t % 10000 < 1500),
        }))
        seq += 1
        await asyncio.sleep(1 / SAMPLE_HZ)


async def demo_script(bench: Bench) -> None:
    """Loop a short 'LED in backwards' conversation. Restarts from the top on reset."""
    while True:
        gen = bench.session.generation
        try:
            await _scene(bench, gen)
        except _Reset:
            pass
        await asyncio.sleep(1)


class _Reset(Exception):
    pass


async def _scene(bench: Bench, gen: int) -> None:
    s, b = bench.session, bench.hub.broadcast

    async def wait(sec: float) -> None:
        await asyncio.sleep(sec)
        if s.generation != gen:
            raise _Reset

    async def state(value: State, detail: str | None = None) -> None:
        if s.generation != gen:
            raise _Reset
        await s.set_state(value, detail)

    await wait(2)
    await state(State.listening)
    await s.say("student", "My LED", final=False)
    await wait(0.6)
    await s.say("student", "My LED won't turn on", final=False)
    await wait(0.6)
    await state(State.transcribing)
    await s.say("student", "My LED won't turn on.")
    await wait(0.5)
    await state(State.thinking)
    await wait(1.2)

    await state(State.speaking)
    await s.say("bench", "Let's find where the power stops. Put the yellow probe anywhere in row 6.")
    await s.expect(ExpectOut(probe="Y", at="6c", expected_mv=5000, tol_mv=250, label="5 V"))
    await b(OverlayOut(mode="replace", items=[
        OverlayItem(id="h1", kind="strip", at="6:a-e", style="probe-Y", pulse=True),
    ]))
    await b(ManualOut(step=1))
    await b(SchematicOut(nets=["n_5v"]))
    await wait(3)
    await state(State.idle)
    await wait(2)

    await s.say("system", "Yellow reads 5.00 V in row 6 ✓")
    await s.expect(ExpectOut(probe="Y", clear=True))
    await b(OverlayOut(mode="replace", items=[
        OverlayItem(id="h1", kind="strip", at="6:a-e", style="good"),
    ]))
    await wait(1)
    await state(State.thinking)
    await wait(1)
    await state(State.speaking)
    await s.say("bench", "Good, power's getting in. Now the blue probe in row 10, after the resistor.")
    await s.expect(ExpectOut(probe="B", at="10c", expected_mv=1900, tol_mv=300, label="LED anode"))
    await b(OverlayOut(mode="add", items=[
        OverlayItem(id="h2", kind="strip", at="10:a-e", style="probe-B", pulse=True),
        OverlayItem(id="a1", kind="arrow", from_="6c", to="10c", style="attention"),
    ]))
    await b(ManualOut(step=3))
    await b(SchematicOut(nets=["n_led_anode"]))
    await wait(3)
    await state(State.idle)
    await wait(2)

    await s.say("system", "Blue reads 4.99 V in row 10. Expected about 1.9 V ✗")
    await s.expect(ExpectOut(probe="B", clear=True))
    await state(State.thinking)
    await wait(1.2)
    await state(State.speaking)
    await s.say("bench", "Hm, 5 volts there. If current were flowing, what would the resistor do to the voltage?")
    await b(OverlayOut(mode="replace", items=[
        OverlayItem(id="h2", kind="strip", at="10:a-e", style="bad"),
        OverlayItem(id="c1", kind="component", ref="D1", style="attention", pulse=True),
        OverlayItem(id="l1", kind="label", at="13d", text="long leg?"),
    ]))
    await wait(4)
    await state(State.idle)
    await wait(3)

    await b(OverlayClearOut())
    await b(SchematicOut(nets=[]))
    await s.say("system", "(demo loops)")
