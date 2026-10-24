"""Text-mode ALTA: talk to the agent by typing, no voice and no browser needed.

    cd server
    uv run python -m bench.cli --lab lab1-led                  # pod auto-detected (or POD_PORT)
    uv run python -m bench.cli --lab lab1-led --pod /dev/ttys012   # the mock pod's port (#9)
    uv run python -m bench.cli --lab lab1-led --pod off        # no pod at all

Type as the student. You'll see ALTA's reply, every tool call it makes, and the probe readings.
Commands: /probes  /event <text>  /reset  /quit
Needs ANTHROPIC_API_KEY in the repo's .env.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time

from .agent import Agent
from .hub import Bench
from .labs import load_labs
from .main import LABS_DIR
from .pod import OFF, PodBridge
from .protocol import PROBES, State

DIM, BOLD, RED, CYAN, RESET = ("\033[2m", "\033[1m", "\033[31m", "\033[36m", "\033[0m") if sys.stdout.isatty() \
    else ("", "", "", "", "")


def probes_line(bench: Bench, pod: PodBridge | None) -> str:
    p = bench.session.probes
    status = "pod connected" if pod and pod.connected else "no pod"
    if not p:
        return f"{DIM}probes: no readings ({status}){RESET}"
    cells = []
    for i, name in enumerate(PROBES):
        mv = p["mv"][i]
        at = bench.session.expects.get(name)
        where = f"@{at.at}" if at else ""
        cells.append(f"{name}{where} " + ("unplugged" if mv == -1 else f"{mv / 1000:.2f} V"))
    return f"{DIM}probes: {'  '.join(cells)}  ({status}){RESET}"


async def run(args) -> int:
    labs = load_labs(LABS_DIR)
    if args.lab not in labs:
        print(f"unknown lab {args.lab!r}; labs: {', '.join(labs) or 'none'}")
        return 2
    bench = Bench(labs)
    bench.session.lab_id = args.lab

    port = args.pod if args.pod is not None else (os.environ.get("POD_PORT") or None)
    pod = None if (port or "").lower() in OFF else PodBridge(bench.bus, port)
    if pod:
        bench.session.pod_command = pod.send
        pod.start(asyncio.get_running_loop())

    agent = Agent(bench, model=args.model, pod_connected=lambda: bool(pod and pod.connected))

    def on_tool(name, args_, result, is_error):
        mark = f"{RED}✗{RESET}" if is_error else "·"
        print(f"  {mark} {CYAN}{name}{RESET} {json.dumps(args_, ensure_ascii=False)}")
        shown = result if isinstance(result, str) else " + ".join(b["type"] for b in result)  # image blocks
        print(f"    {DIM}→ {shown[:300]}{RESET}")

    async def speak(text):
        s = bench.session
        await s.set_state(State.speaking)
        await s.say("bench", text)
        print(f"{BOLD}bench>{RESET} {text}")
        await s.set_state(State.idle)

    agent.on_tool_call = on_tool
    agent.speak = speak
    core = asyncio.create_task(bench.run())

    print(f"ALTA text mode · {labs[args.lab].data.get('title', args.lab)} · model {agent.model}")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(f"{RED}ANTHROPIC_API_KEY is not set (put it in the repo's .env). Replies will fail.{RESET}")
    print(f"{DIM}Type as the student. /probes /event <text> /reset /quit{RESET}")
    if pod:
        await asyncio.sleep(1.0)  # give the pod a moment to say hello
    print(probes_line(bench, pod))

    try:
        while True:
            try:
                line = (await asyncio.to_thread(input, "you> ")).strip()
            except EOFError:
                break
            if not line:
                continue
            if line in ("/quit", "/exit", "/q"):
                break
            if line == "/probes":
                print(probes_line(bench, pod))
                continue
            if line == "/reset":
                await bench.reset()
                print(f"{DIM}(new student: conversation cleared){RESET}")
                continue
            n_before, t0 = len(agent.usage), time.monotonic()
            if line.startswith("/event "):
                said = await agent.turn(event=line[len("/event "):])
                if said is None:
                    print(f"{DIM}bench> <silent>{RESET}")
            else:
                await agent.turn(line)
            calls = agent.usage[n_before:]
            cached = sum(u.cache_read_input_tokens or 0 for u in calls)
            print(f"{DIM}[{len(calls)} call(s) · {time.monotonic() - t0:.1f} s · cache read {cached:,} tok]{RESET}")
            print(probes_line(bench, pod))
    finally:
        core.cancel()
        if pod:
            pod.stop()
    return 0


def main() -> None:
    p = argparse.ArgumentParser(prog="bench.cli", description="Talk to ALTA by typing.")
    p.add_argument("--lab", default="lab1-led")
    p.add_argument("--pod", default=None, help="serial port, or 'off' (default: POD_PORT or auto-detect)")
    p.add_argument("--model", default=None, help="default: BENCH_MODEL or claude-opus-5-5")
    p.add_argument("-v", "--verbose", action="store_true", help="show server logs")
    args = p.parse_args()
    logging.getLogger().setLevel(logging.INFO if args.verbose else logging.WARNING)
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
