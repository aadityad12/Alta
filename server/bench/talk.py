"""Talk to Bench out loud, with no pod and no screen: the real mic, Cartesia speech-to-text, Claude, Cartesia
voice and probe monitor, with the mock pod's voltages standing in for the board.

    cd server
    uv run python -m bench.talk                                   # Lab 1, LED in backwards, BENCH_MODEL
    uv run python -m bench.talk --model claude-opus-5-5           # judge it on the demo model
    uv run python -m bench.talk --lab lab2-light --fault wrong_resistor_220

Enter = the talk button: press Enter, speak, press Enter again. Pressing it while Bench talks cuts it off.
You are also the student's hands on the board (type, then Enter):
    Y 10c          plug the yellow probe into hole 10c (B, G, W too)    unplug Y
    fix            fix the staged fault                                  fault <id>   stage another
    light 0 / 1    cover the light sensor / shine a light on it (Lab 2)  light 0.5    room light
    probes         what each probe reads                                 reset        new student
    say <text>     type to Bench instead of talking                      quit
Probes start unplugged, so put them where Bench asks: it reacts by itself once a reading settles.
"""

import argparse
import asyncio
import logging
import os
import sys
import time

from . import bus as ev
from .agent import Agent
from .bus import Event
from .hub import Bench
from .labs import load_labs
from .main import LABS_DIR
from .monitor import NAMES, Monitor
from .protocol import PROBES, State, TextIn, TranscriptOut
from .scenarios import mock_pod
from .voice_in import CartesiaSTT, Mic, VoiceIn, mic_device
from .voice_out import Player, Speaker, output_device

DIM, BOLD, CYAN, GREEN, YELLOW, RESET = ("\033[2m", "\033[1m", "\033[36m", "\033[32m", "\033[33m", "\033[0m") \
    if sys.stdout.isatty() else ("",) * 6


def out(line: str = "") -> None:
    print(f"\r{line}", flush=True)


async def run(args) -> int:
    labs = load_labs(LABS_DIR)
    lab = labs[args.lab]
    faults = [f["id"] for f in lab.data["faults"]]
    if args.fault not in faults:
        out(f"unknown fault {args.fault!r}; {lab.id} has: {', '.join(faults)}")
        return 2
    bench = Bench(labs)
    bench.session.lab_id = lab.id
    if bench.recorder:
        bench.recorder.start(lab.id)

    # ---- the board: the mock pod's model, sampled every 50 ms onto the bus like the real pod ----
    pod = mock_pod.MockPod(LABS_DIR, None, None)
    os.close(pod.master)
    os.close(pod.slave)
    pod.load_lab(lab.id, args.fault)
    pod.command("unplug all")

    async def sampler():
        while True:
            r = [pod.reading(p, mock_pod.VCC_MV) for p in PROBES]
            bench.bus.publish(Event(ev.POD_SAMPLE, {"mv": [x[0] for x in r], "lo": [x[1] for x in r],
                                                    "hi": [x[2] for x in r], "vcc": mock_pod.VCC_MV, "btn": 0}))
            await asyncio.sleep(mock_pod.TICK_S)

    # ---- what you see: the conversation, Bench's tool calls, and timing ----
    released = [0.0]
    real_broadcast = bench.session.broadcast

    async def show(msg):
        if isinstance(msg, TranscriptOut) and msg.final:
            if msg.role == "student":
                out(f"{BOLD}you>{RESET} {msg.text}")
            else:
                out(f"{BOLD}{GREEN}bench>{RESET} {msg.text}")
        await real_broadcast(msg)

    bench.session.broadcast = show
    record = bench.session.record

    def timed(kind, **fields):
        record(kind, **fields)
        if kind == "ptt" and not fields.get("down"):
            released[0] = time.monotonic()
        elif kind == "stt" and released[0]:
            out(f"{DIM}  (heard you in {fields['ms'] / 1000:.2f} s){RESET}")
        elif kind == "first_audio" and released[0]:
            out(f"{DIM}  (Bench started talking {time.monotonic() - released[0]:.2f} s after you let go){RESET}")
            released[0] = 0.0
        elif kind == "monitor":
            out(f"{YELLOW}  [probe monitor] {fields['text']}{RESET}")

    bench.session.record = timed

    agent = Agent(bench, model=args.model, pod_connected=lambda: True)

    def on_tool(name, inp, result, is_error):
        if name in ("ask_for_probe", "record_diagnosis", "highlight", "read_probes"):
            short = {k: v for k, v in inp.items() if k in ("probe", "at", "fault_id", "hint_level", "resolved")}
            out(f"{CYAN}  · {name} {short if short else ''}{RESET}{' (error)' if is_error else ''}")

    agent.on_tool_call = on_tool

    # ---- the voice: the same wiring as the server (bench/main.py) ----
    player = Player(output_device(os.environ.get("SPEAKER_DEVICE", "")))
    player.open()
    speaker = Speaker(bench.session, player)
    await speaker.connect()
    agent.speak, agent.speak_stream = speaker.say, speaker.speak
    bench.speaker = speaker
    mic = Mic(mic_device(os.environ.get("MIC_DEVICE", "")))
    mic.open()
    bench.voice = VoiceIn(bench.session, mic, CartesiaSTT(), on_transcript=agent.turn, speak=speaker.say)

    tasks = [asyncio.create_task(c) for c in (bench.run(), agent.run(), Monitor(bench).run(), sampler(),
                                              agent.keep_warm())]
    fault = next(f for f in lab.data["faults"] if f["id"] == args.fault)
    out(f"{BOLD}Bench, out loud{RESET} · {lab.data.get('title')} · staged fault: {fault['name']}"
        f" · model {agent.model}")
    out(f"{DIM}Enter = talk button (press, speak, press again). Board: Y 10c · unplug Y · fix · light 0/1 · "
        f"probes · say <text> · reset · quit{RESET}")
    out(f"{DIM}The student's problem: \"{fault['symptom']}\" Try saying: \"Hi, I built the circuit but {fault['symptom'][0].lower() + fault['symptom'][1:] if not fault['symptom'][1:2].isupper() else fault['symptom']} Can you help?\"{RESET}")

    talking = False
    try:
        while True:
            prompt = "  [talking… press Enter to stop] " if talking else "> "
            line = (await asyncio.to_thread(input, prompt)).strip()
            if not line:
                talking = not talking
                if talking and bench.session.state not in (State.idle, State.speaking, State.error):
                    talking = False
                    out(f"{DIM}  (Bench is {bench.session.state.value}; wait a moment){RESET}")
                    continue
                bench.bus.publish(Event(ev.PTT, talking))
                continue
            if talking:  # typed something while "holding" the button: let go first
                talking = False
                bench.bus.publish(Event(ev.PTT, False))
            word = line.split()[0].lower()
            if word in ("quit", "exit", "q"):
                break
            if word == "probes":
                for p in PROBES:
                    where = pod.probes[p]
                    mv = pod.reading(p, mock_pod.VCC_MV)[0]
                    out(f"  {NAMES[p]:<7} {where or 'unplugged':<9} {'' if not where else f'{mv / 1000:.2f} V'}")
            elif word == "reset":
                await bench.reset()
                pod.load_lab(lab.id, args.fault)
                pod.command("unplug all")
                out(f"{DIM}  (new student: conversation cleared, fault staged again, probes out){RESET}")
            elif word == "say":
                bench.bus.publish(Event(ev.UI, TextIn(type="text", text=line[4:].strip())))  # the agent captions it
            else:
                try:
                    pod.command(line)
                except (ValueError, IndexError) as e:
                    out(f"  ? {e or 'unknown command'}")
                    continue
                if word.upper() in PROBES:
                    p = word.upper()
                    out(f"{DIM}  ({NAMES[p].lower()} probe in {pod.probes[p]}: {pod.describe(p)}){RESET}")
                elif word == "fix":
                    out(f"{DIM}  (fixed: the board is now the correct circuit){RESET}")
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        for t in tasks:
            t.cancel()
        speaker.stop()
        await speaker.close()
        player.close()
        mic.close()
    return 0


def main() -> None:
    p = argparse.ArgumentParser(prog="bench.talk", description="Talk to Bench out loud, with the mock pod.")
    p.add_argument("--lab", default="lab1-led")
    p.add_argument("--fault", default="led_reversed")
    p.add_argument("--model", default=None, help="default: BENCH_MODEL from .env")
    p.add_argument("-v", "--verbose", action="store_true", help="show server logs too")
    args = p.parse_args()
    logging.getLogger().setLevel(logging.INFO if args.verbose else logging.ERROR)
    for key in ("ANTHROPIC_API_KEY", "CARTESIA_API_KEY"):
        if not os.environ.get(key):
            sys.exit(f"{key} is not set (.env)")
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
