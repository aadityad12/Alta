"""Pre-demo check (#45, #46): is everything ALTA needs ready on this laptop? Run it before `scripts/dev.sh`.

    cd server
    uv run python -m bench.preflight              # every check, ~5 s; exits 1 if anything is broken
    uv run python -m bench.preflight --hear       # also say "ALTA is ready." through the speaker
    uv run python -m bench.preflight --no-pod     # skip the pod (no pod at this laptop)

Each line is ✓ (ready), ! (works, but not how we demo) or ✗ (broken), with the one-line fix.
It makes real calls: one Claude pre-warm with the demo settings (max_tokens=0, nothing generated), one
short TTS line and one half-second STT clip. Run it with the server stopped: the server holds the pod's port.
"""

import argparse
import asyncio
import glob
import json
import logging
import os
import shutil
import socket
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .main import LABS_DIR, REPO_ROOT  # loads .env

DEMO_MODEL = "claude-opus-5-5"
DEMO_LAB = "lab1-led"
POD_WAIT_S = 4.0  # opening the port resets the Uno; it says hello about 1-2 s later
OK, WARN, BAD = "ok", "warn", "bad"

GREEN, YELLOW, RED, DIM, RESET = ("\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[0m") if sys.stdout.isatty() \
    else ("", "", "", "", "")
MARK = {OK: f"{GREEN}✓{RESET}", WARN: f"{YELLOW}!{RESET}", BAD: f"{RED}✗{RESET}"}


@dataclass
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""

    def line(self) -> str:
        fix = f"\n      {DIM}→ {self.fix}{RESET}" if self.fix and self.status != OK else ""
        return f"  {MARK[self.status]} {self.name:<10} {self.detail}{fix}"


def _err(e: BaseException) -> str:
    text = str(e).strip().splitlines()[0] if str(e).strip() else ""
    return f"{type(e).__name__}: {text}"[:160] if text else type(e).__name__


# ---------- settings and files ----------

def check_env_file(root: Path = REPO_ROOT) -> Check:
    if (root / ".env").is_file():
        return Check(".env", OK, str(root / ".env"))
    return Check(".env", BAD, "missing", "cp .env.example .env and fill in the two API keys")


def check_settings(env=os.environ) -> list[Check]:
    from .voice_out import VOICES, pick_voice

    model, speed = env.get("BENCH_MODEL", "").strip() or DEMO_MODEL, env.get("BENCH_SPEED", "").strip()
    out = []
    if model == DEMO_MODEL and speed == "fast":
        out.append(Check("model", OK, f"{model} (fast mode)"))
    else:
        out.append(Check("model", WARN, f"{model}{' (fast mode)' if speed == 'fast' else ''}: not the demo setting",
                         f"set BENCH_MODEL={DEMO_MODEL} and BENCH_SPEED=fast in .env"))
    choice = env.get("BENCH_VOICE", "").strip().lower()
    if env.get("CARTESIA_VOICE_ID", "").strip():
        out.append(Check("voice", OK, f"custom voice {env['CARTESIA_VOICE_ID'].strip()}"))
    elif choice and choice not in VOICES:
        out.append(Check("voice", WARN, f"BENCH_VOICE={choice!r} isn't man or woman; using the man's",
                         "set BENCH_VOICE=man or BENCH_VOICE=woman"))
    else:
        name, vid = pick_voice()
        out.append(Check("voice", OK, f"{name} ({choice or 'man, the default'})"))
    for key in ("ANTHROPIC_API_KEY", "CARTESIA_API_KEY"):
        if not env.get(key, "").strip():
            out.append(Check(key.split("_")[0].lower(), BAD, f"{key} is empty", f"put {key} in .env"))
    return out


def check_labs(labs_dir: Path = LABS_DIR):
    from .labs import load_labs

    labs = load_labs(labs_dir)
    if DEMO_LAB not in labs:
        return Check("labs", BAD, f"{DEMO_LAB} didn't load ({', '.join(labs) or 'no labs'})",
                     "run `uv run labs/validate.py` from the repo root to see what's wrong"), labs
    return Check("labs", OK, ", ".join(labs)), labs


def check_web(root: Path = REPO_ROOT) -> Check:
    if not shutil.which("npm"):
        return Check("web", BAD, "npm not found", "brew install node")
    if not (root / "web" / "node_modules").is_dir():
        return Check("web", WARN, "web/node_modules missing", "scripts/dev.sh installs it (needs internet once)")
    return Check("web", OK, "node + web/node_modules")


def port_in_use(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def check_ports(ports=(8000, 5173)) -> Check:
    busy = [p for p in ports if port_in_use(p)]
    if busy:
        return Check("ports", WARN, f"already in use: {', '.join(f':{p}' for p in busy)} (ALTA already running?)",
                     "stop the old scripts/dev.sh (Ctrl-C) before starting a fresh one")
    return Check("ports", OK, "8000 and 5173 free")


# ---------- audio devices ----------

def check_audio(env=os.environ) -> list[Check]:
    import sounddevice as sd

    from .voice_in import MIC_OFF, mic_device
    from .voice_out import output_device

    out = []
    for name, key, kind, pick in (("mic", "MIC_DEVICE", "input", mic_device), ("speaker", "SPEAKER_DEVICE", "output",
                                                                                  output_device)):
        value = env.get(key, "")
        if value.strip().lower() in MIC_OFF:
            out.append(Check(name, WARN, f"{key}={value} (turned off)", f"empty {key} in .env to use the default"))
            continue
        try:
            d = sd.query_devices(pick(value), kind=kind)
            out.append(Check(name, OK, d["name"]))
        except Exception as e:
            out.append(Check(name, BAD, f"{key}={value!r}: {_err(e)}",
                             f"pick one from `uv run python -m bench.voice_{'in' if kind == 'input' else 'out'} "
                             f"--list-devices`"))
    return out


# ---------- network services ----------

async def check_claude(lab, client=None) -> Check:
    """A real pre-warm with the exact demo settings (model, fast mode, tools, this lab's prompt)."""
    import anthropic

    from .agent import Agent
    from .hub import Bench

    bench = Bench({lab.id: lab})
    bench.session.lab_id = lab.id
    agent = Agent(bench, client=client)
    t0 = time.monotonic()
    try:
        await asyncio.wait_for(agent.prewarm(), 15)
    except anthropic.AuthenticationError:
        return Check("claude", BAD, "the API key was rejected (401)", "check ANTHROPIC_API_KEY in .env")
    except (anthropic.APIConnectionError, asyncio.TimeoutError) as e:
        return Check("claude", BAD, f"can't reach the API ({type(e).__name__})", "check the Wi-Fi / hotspot")
    except Exception as e:
        return Check("claude", BAD, _err(e), "fast mode or the model may be unavailable: try BENCH_SPEED= (empty)")
    return Check("claude", OK, f"{agent.model}{' fast' if agent.speed == 'fast' else ''} · lab prompt cached in "
                               f"{(time.monotonic() - t0) * 1000:.0f} ms")


async def check_tts(client=None) -> tuple[Check, bytes]:
    from .voice_out import OUTPUT_FORMAT, TTS_MODEL, pick_voice

    name, vid = pick_voice()
    t0 = time.monotonic()
    try:
        if client is None:
            from cartesia import AsyncCartesia

            client = AsyncCartesia(api_key=os.environ.get("CARTESIA_API_KEY"), timeout=10, max_retries=1)
        resp = await client.tts.generate(model_id=TTS_MODEL, transcript="ALTA is ready.", voice={"mode": "id", "id": vid},
                                         output_format=OUTPUT_FORMAT, language="en")
        pcm = await resp.read()
    except Exception as e:
        return Check("tts", BAD, _err(e), "check CARTESIA_API_KEY and the internet; ALTA would be captions only"), b""
    if len(pcm) < 1000:
        return Check("tts", BAD, f"only {len(pcm)} bytes of audio came back", "check the voice id"), b""
    return Check("tts", OK, f"{name} · {TTS_MODEL} · {len(pcm) / 2 / OUTPUT_FORMAT['sample_rate']:.1f} s of audio in "
                            f"{(time.monotonic() - t0) * 1000:.0f} ms"), pcm


async def check_stt(stt=None) -> Check:
    from .voice_in import SAMPLE_RATE, CartesiaSTT, wav_bytes

    stt = stt or CartesiaSTT()
    t0 = time.monotonic()
    try:
        await asyncio.wait_for(stt(wav_bytes(np.zeros(SAMPLE_RATE // 2, dtype=np.int16))), 10)
    except Exception as e:
        return Check("stt", BAD, _err(e), "check CARTESIA_API_KEY and the internet; students can still type (/)")
    return Check("stt", OK, f"{stt.model} answered in {(time.monotonic() - t0) * 1000:.0f} ms")


# ---------- the pod ----------

def find_pod(port: str | None) -> str | None:
    from .pod import AUTODETECT

    if port:
        return port if os.path.exists(port) else None
    found = sorted(p for pattern in AUTODETECT for p in glob.glob(pattern))
    return found[0] if found else None


def describe_sample(msg: dict) -> str:
    from .protocol import PROBES

    probes = "  ".join(f"{n} {'unplugged' if mv == -1 else f'{mv / 1000:.2f} V'}" for n, mv in zip(PROBES, msg["mv"]))
    return f"{probes} · button {'down' if msg.get('btn') else 'up'}"


def check_pod(port: str | None, wait_s: float = POD_WAIT_S) -> Check:
    import serial

    from .pod import BAUD

    path = find_pod(port)
    if path is None:
        where = f"POD_PORT={port}" if port else "no /dev/cu.usbmodem* found"
        return Check("pod", BAD, f"not found ({where})", "plug the Uno's USB cable in (or fix POD_PORT in .env)")
    try:
        ser = serial.Serial(path, BAUD, timeout=0.05)
    except (serial.SerialException, OSError) as e:
        return Check("pod", BAD, f"{path}: can't open ({_err(e)})",
                     "something else has the port open: close the Arduino IDE serial monitor / live.py")
    hello, sample, buf, pinged = None, None, b"", False
    end = time.monotonic() + wait_s
    try:
        while time.monotonic() < end and not (hello and sample):
            buf += ser.read(ser.in_waiting or 1)
            *lines, buf = buf.split(b"\n")
            for raw in lines:
                try:
                    msg = json.loads(raw.decode("utf-8", "replace"))
                except ValueError:
                    continue
                if not isinstance(msg, dict):
                    continue
                if "hello" in msg or "pong" in msg:
                    hello = msg
                elif isinstance(msg.get("mv"), list) and len(msg["mv"]) == 4:
                    sample = msg
                    if not hello and not pinged:  # already booted (no reset on open): ask for its version
                        pinged = True
                        ser.write(b"PING\n")
    finally:
        ser.close()
    if not sample:
        return Check("pod", BAD, f"{path}: no readings in {wait_s:.0f} s",
                     "re-flash the firmware: `uv run firmware/sanity/check_pod.py --upload`")
    fw = f"fw {hello.get('fw')} · " if hello else ""
    return Check("pod", OK, f"{path} · {fw}{describe_sample(sample)}")


# ---------- run ----------

async def _play(pcm: bytes) -> None:
    import sounddevice as sd

    from .voice_out import TTS_RATE, output_device

    audio = np.frombuffer(pcm, dtype=np.int16)
    await asyncio.to_thread(lambda: (sd.play(audio, TTS_RATE, device=output_device(os.environ.get("SPEAKER_DEVICE"))),
                                     sd.wait()))


async def run(args) -> int:
    print(f"ALTA preflight · {REPO_ROOT}")
    checks = [check_env_file(), *check_settings()]
    lab_check, labs = check_labs()
    checks += [lab_check, check_web(), check_ports(), *check_audio()]
    for c in checks:
        print(c.line())

    have = {k: bool(os.environ.get(k, "").strip()) for k in ("ANTHROPIC_API_KEY", "CARTESIA_API_KEY")}
    pending = []
    if have["ANTHROPIC_API_KEY"] and DEMO_LAB in labs:
        pending.append(check_claude(labs[DEMO_LAB]))
    if have["CARTESIA_API_KEY"]:
        pending += [check_tts(), check_stt()]
    pcm = b""
    for result in await asyncio.gather(*pending):
        c, pcm = result if isinstance(result, tuple) else (result, pcm)
        checks.append(c)
        print(c.line())

    if args.no_pod:
        print(f"  {DIM}- pod        skipped (--no-pod){RESET}")
    elif port_in_use(8000):
        c = Check("pod", WARN, "not checked: ALTA's server is running and holds the port",
                  "look at the probes on /brain, or stop the server and run this again")
        checks.append(c)
        print(c.line())
    else:
        c = await asyncio.to_thread(check_pod, os.environ.get("POD_PORT", "").strip() or None)
        checks.append(c)
        print(c.line())

    if args.hear and pcm:
        print(f"  {DIM}playing \"ALTA is ready.\"…{RESET}")
        try:
            await _play(pcm)
        except Exception as e:
            print(f"  {MARK[BAD]} speaker    {_err(e)}")

    bad = [c.name for c in checks if c.status == BAD]
    warn = [c.name for c in checks if c.status == WARN]
    if bad:
        print(f"{RED}Not ready: {', '.join(bad)}.{RESET}")
    elif warn:
        print(f"{YELLOW}Ready, with warnings: {', '.join(warn)}.{RESET} Next: scripts/dev.sh")
    else:
        print(f"{GREEN}Ready for the demo.{RESET} Next: scripts/dev.sh")
    return 1 if bad else 0


def main() -> None:
    p = argparse.ArgumentParser(prog="bench.preflight", description="Is this laptop ready to demo ALTA?")
    p.add_argument("--hear", action="store_true", help='also say "ALTA is ready." through the speaker')
    p.add_argument("--no-pod", action="store_true", help="skip the pod check")
    logging.getLogger().setLevel(logging.WARNING)  # the checks print their own results
    logging.getLogger("anthropic").setLevel(logging.ERROR)
    sys.exit(asyncio.run(run(p.parse_args())))


if __name__ == "__main__":
    main()
