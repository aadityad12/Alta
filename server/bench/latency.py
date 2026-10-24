"""End-to-end latency check (#22): button release -> first audio, without the pod, a mic or a person.

    cd server
    uv run python -m bench.latency                 # 10 turns, BENCH_MODEL / BENCH_SPEED from .env
    uv run python -m bench.latency --fast          # Opus fast mode
    uv run python -m bench.latency --turns 10 --fault led_reversed

Every stage is the real one except the hardware: the student's line is spoken by macOS `say` into a 16 kHz
WAV (the mic), transcribed by Cartesia (#18), answered by the agent against the mock pod's voltages (#9),
and spoken by Cartesia (#19) into a player that only notes when the first audio arrives (+ the 26 ms the
real output device adds). The student is the one from bench.scenarios: it plugs probes where asked, answers
what it sees, and fixes the fault once ALTA points at it.
"""

import argparse
import asyncio
import logging
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .agent import Agent
from .hub import Bench
from .labs import load_labs
from .main import LABS_DIR
from .protocol import PROBES, State
from .scenarios import Step, Student, mock_pod
from .voice_in import CartesiaSTT
from .voice_out import Speaker

DEVICE_LATENCY_S = 0.026  # the real speaker's output latency, measured in #19


class TimingPlayer:
    """Stands in for the sound card: notes when audio arrives, plays nothing."""

    latency = DEVICE_LATENCY_S

    def __init__(self) -> None:
        self.first: float | None = None

    def write(self, pcm) -> None:
        if self.first is None and len(pcm):
            self.first = time.monotonic()

    def clear(self) -> None:
        pass

    def pending(self) -> int:
        return 0


def speech_wav(text: str) -> bytes:
    """The student's line as a 16 kHz mono WAV, like the mic's clip (macOS `say`)."""
    with tempfile.NamedTemporaryFile(suffix=".wav") as f:
        subprocess.run(["say", "-o", f.name, "--file-format=WAVE", "--data-format=LEI16@16000", text], check=True)
        return Path(f.name).read_bytes()


async def measure(args) -> list[dict]:
    labs = load_labs(LABS_DIR)
    lab = labs[args.lab]
    fault = next(f for f in lab.data["faults"] if f["id"] == args.fault)
    bench = Bench({lab.id: lab})
    bench.session.lab_id = lab.id

    async def quiet(msg):
        pass

    bench.hub.broadcast = bench.session.broadcast = quiet
    marks: list[tuple[float, str]] = []
    bench.session.record = lambda kind, **f: marks.append((time.monotonic(), kind))

    import anthropic

    client = anthropic.AsyncAnthropic(max_retries=1)
    agent = Agent(bench, client=client, speed="fast" if args.fast else None, pod_connected=lambda: True)
    player = TimingPlayer()
    speaker = Speaker(bench.session, player)
    await speaker.connect()
    agent.speak, agent.speak_stream = speaker.say, speaker.speak
    bench.speaker = speaker
    stt = CartesiaSTT()
    student = Student(lab.data, fault, rng_seed=1, client=client)
    await agent.prewarm()  # what the server does at startup

    def board(cmds):
        for c in cmds:
            if not c.startswith("sleep"):
                student.pod.command(c)
        r = [student.pod.reading(p, mock_pod.VCC_MV) for p in PROBES]
        bench.session.probes = {"mv": [x[0] for x in r], "lo": [x[1] for x in r], "hi": [x[2] for x in r],
                                "vcc": mock_pod.VCC_MV, "btn": 0}
        bench.session.probes_at = time.monotonic()

    board([])
    print(f"{args.turns} turns · {agent.model}{' fast' if args.fast else ''} · filler after {agent.filler_s} s",
          file=sys.stderr)
    rows, line = [], student.opener()
    for n in range(1, args.turns + 1):
        wav = await asyncio.to_thread(speech_wav, line)
        bench.session.state = State.idle
        player.first, marks[:] = None, []
        t0 = time.monotonic()  # the button comes up
        await bench.session.set_state(State.listening)
        await bench.session.set_state(State.transcribing)
        text = await stt(wav)
        t_stt = time.monotonic()
        step = Step("student", text, [])
        agent.on_tool_call = lambda name, inp, res, err: step.tools.append(
            {"name": name, "input": inp, "error": err, "result": res if isinstance(res, str) else ""})
        step.reply = await agent.turn(text)
        audio = [t for t, k in marks if k == "first_audio"]
        first_text = next((t for t, k in marks if k == "first_text"), None)
        filler = any(k == "filler" for _, k in marks)
        row = {"turn": n, "heard": text, "stt": t_stt - t0,
               "first_text": first_text - t0 if first_text else None,
               "first_audio": player.first + DEVICE_LATENCY_S - t0 if player.first else None,
               "reply_audio": (audio[1] if filler and len(audio) > 1 else (audio[0] if audio else None)),
               "filler": filler, "reply": step.reply}
        if row["reply_audio"] is not None:
            row["reply_audio"] = row["reply_audio"] + DEVICE_LATENCY_S - t0
        rows.append(row)
        fmt = lambda v: f"{v:.2f}" if v is not None else "–"
        print(f"  {n:>2}. stt {fmt(row['stt'])} · first text {fmt(row['first_text'])} · first audio "
              f"{fmt(row['first_audio'])}{' (filler)' if filler else ''} · reply audio {fmt(row['reply_audio'])}"
              f"  | {text!r} → {step.reply!r}", file=sys.stderr)
        did = student.act(step)
        board(did)
        line = await student.say_next(step, did)
        if line is None or (student.fixed and any(t["input"].get("resolved") for t in step.tools
                                                  if t["name"] == "record_diagnosis")):
            line = "Thanks! Can we go over why that happened?"
    await speaker.close()
    return rows


def report(rows: list[dict]) -> str:
    def col(key):
        v = sorted(r[key] for r in rows if r[key] is not None)
        if not v:
            return "–"
        return f"{statistics.median(v):.2f} / {v[min(len(v) - 1, round(0.9 * (len(v) - 1)))]:.2f} / {v[-1]:.2f}"

    fillers = sum(r["filler"] for r in rows)
    return "\n".join([
        f"From button release, {len(rows)} turns (median / p90 / max, s):",
        f"| transcript | first Claude text | first audio | reply audio | filler used |",
        f"|---|---|---|---|---|",
        f"| {col('stt')} | {col('first_text')} | {col('first_audio')} | {col('reply_audio')} | {fillers}/{len(rows)} |",
    ])


def main() -> None:
    p = argparse.ArgumentParser(prog="bench.latency", description="Measure button release -> first audio.")
    p.add_argument("--turns", type=int, default=10)
    p.add_argument("--lab", default="lab1-led")
    p.add_argument("--fault", default="led_reversed")
    p.add_argument("--fast", action="store_true", help="Opus fast mode")
    args = p.parse_args()
    logging.basicConfig(level=logging.WARNING)
    if not os.environ.get("CARTESIA_API_KEY"):
        sys.exit("CARTESIA_API_KEY is not set (.env)")
    print(report(asyncio.run(measure(args))))


if __name__ == "__main__":
    main()
