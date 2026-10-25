"""FastAPI app + /ws hub."""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from . import bus as ev
from . import ta
from .agent import Agent
from .brain import MockBoard, mount
from .bus import Event
from .hub import Bench
from .labs import load_labs
from .monitor import Monitor
from .pod import OFF, PodBridge
from .protocol import BadMessage, ErrorOut, parse_inbound
from .voice_in import MIC_OFF, CartesiaSTT, Mic, VoiceIn, mic_device
from .voice_out import Player, Speaker, output_device

REPO_ROOT = Path(__file__).resolve().parents[2]
LABS_DIR = REPO_ROOT / "labs"
DEMO_LABS_DIR = Path(__file__).resolve().parent / "demo_labs"

load_dotenv(REPO_ROOT / ".env")
logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s: %(message)s")
log = logging.getLogger("bench")


def create_app(
    *, demo_ui: bool | None = None, labs_dir: Path = LABS_DIR, pod_port: str | None = None, mic: str | None = None,
    speaker: str | None = None,
) -> FastAPI:
    """pod_port: serial device path, "off" for no pod, or None to use POD_PORT / auto-detect.
    mic / speaker: device index or name, "off" for none, or None to use MIC_DEVICE / SPEAKER_DEVICE
    (empty = the system default). With no speaker, ALTA's replies are captions only."""
    if demo_ui is None:
        demo_ui = os.environ.get("BENCH_DEMO_UI") == "1"
    if pod_port is None:
        pod_port = os.environ.get("POD_PORT", "").strip() or None
    roots = [labs_dir, DEMO_LABS_DIR] if demo_ui else [labs_dir]
    bench = Bench(load_labs(*roots))
    mock_board = not demo_ui and (pod_port or "").lower() == "mock"  # the mock pod in-process, for /brain
    use_pod = not demo_ui and not mock_board and (pod_port or "").lower() not in OFF
    pod = PodBridge(bench.bus, pod_port) if use_pod else None
    if pod:
        bench.session.pod_command = pod.send
    agent = None if demo_ui else Agent(bench, pod_connected=lambda: mock_board or bool(pod and pod.connected))
    monitor = Monitor(bench) if agent else None  # probe changes -> agent turns, no button press (#21)
    if mic is None:
        mic = os.environ.get("MIC_DEVICE", "")
    use_mic = agent is not None and mic.strip().lower() not in MIC_OFF
    if speaker is None:
        speaker = os.environ.get("SPEAKER_DEVICE", "")
    use_speaker = agent is not None and speaker.strip().lower() not in MIC_OFF

    async def open_speaker() -> Speaker | None:
        player = Player(output_device(speaker))
        try:
            player.open()
        except Exception as e:
            log.error("speaker unavailable (%s); replies are captions only. SPEAKER_DEVICE=%r, see "
                      "`python -m bench.voice_out --list-devices`", e, speaker)
            return None
        if not os.environ.get("CARTESIA_API_KEY"):
            log.warning("CARTESIA_API_KEY is not set (.env); replies are captions only")
        sp = Speaker(bench.session, player)
        try:
            await sp.connect()  # warm the websocket so the first reply doesn't pay for it
        except Exception as e:
            log.warning("tts connect failed (%r); will retry on the first reply", e)
            await bench.session.health.down("voice", f"tts connect: {type(e).__name__}")
        log.info("voice: %s (%s) · %s", sp.voice_name, sp.voice_id, sp.model)
        agent.speak, agent.speak_stream = sp.say, sp.speak
        return sp

    def open_voice() -> VoiceIn | None:
        m = Mic(mic_device(mic))
        try:
            m.open()
        except Exception as e:
            log.error("mic unavailable (%s); the talk button won't record. MIC_DEVICE=%r, see "
                      "`python -m bench.voice_in --list-devices`", e, mic)
            return None
        if not os.environ.get("CARTESIA_API_KEY"):
            log.warning("CARTESIA_API_KEY is not set (.env); speech-to-text will fail")
        return VoiceIn(bench.session, m, CartesiaSTT(), on_transcript=agent.turn, speak=lambda t: agent.speak(t))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        log.info("labs: %s%s", ", ".join(bench.labs) or "none", " (demo UI mode)" if demo_ui else "")
        tasks = [asyncio.create_task(bench.run())]
        if demo_ui:
            from .demo import run_demo
            tasks.append(asyncio.create_task(run_demo(bench)))
        if pod:
            pod.start(asyncio.get_running_loop())
        if board:
            tasks.append(asyncio.create_task(board.run()))
        health = bench.session.health
        if pod:
            health.waiting("pod")  # down until the pod says hello
        elif not mock_board:
            health.off("pod")
        if not agent or not os.environ.get("ANTHROPIC_API_KEY"):
            health.off("ai")
        if not agent or not os.environ.get("CARTESIA_API_KEY") or not (use_speaker or use_mic):
            health.off("voice")
        if use_speaker:
            bench.speaker = await open_speaker()
            if bench.speaker:
                tasks.append(asyncio.create_task(bench.speaker.keep_fresh()))  # TTS idle timeout, dead speaker
        if use_mic:
            bench.voice = open_voice()
            if bench.voice:
                tasks.append(asyncio.create_task(bench.voice.keep_alive()))  # reopen a mic whose device dropped
        if agent:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                log.warning("ANTHROPIC_API_KEY is not set (.env); ALTA will answer with its fallback line")
            log.info("agent model: %s%s", agent.model, " (fast mode)" if agent.speed == "fast" else "")
            tasks.append(asyncio.create_task(agent.run()))
            tasks.append(asyncio.create_task(monitor.run()))
            if os.environ.get("ANTHROPIC_API_KEY"):
                tasks.append(asyncio.create_task(agent.keep_warm()))  # prompt cache warm for the current lab (#22)
        yield
        if pod:
            pod.stop()
        if bench.voice:
            bench.voice.mic.close()
        if bench.speaker:
            await bench.speaker.close()
            bench.speaker.player.close()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(title="ALTA", lifespan=lifespan)
    board = MockBoard(bench, labs_dir) if mock_board else None
    app.state.brain = mount(app, bench, agent, board)  # dev page: /brain
    app.state.ta = ta.Room(bench)
    ta.mount(app, app.state.ta)  # TA dashboard: /ta (#24)
    app.state.bench = bench
    app.state.pod = pod
    app.state.agent = agent
    app.state.monitor = monitor

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/labs")
    def list_labs() -> list[dict]:
        return [{"id": lab.id, "title": lab.data.get("title", lab.id)} for lab in bench.labs.values()]

    @app.get("/labs/{lab_id}/{path:path}")
    def lab_file(lab_id: str, path: str) -> FileResponse:
        lab = bench.labs.get(lab_id)
        if lab is None:
            raise HTTPException(404, "unknown lab")
        f = (lab.dir / path).resolve()
        if not f.is_relative_to(lab.dir.resolve()) or not f.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(f)

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        await bench.connect(ws)
        try:
            while True:
                text = await ws.receive_text()
                try:
                    msg = parse_inbound(json.loads(text))
                except BadMessage as e:
                    await bench.hub.send(ws, ErrorOut(message=str(e)))
                    continue
                except ValueError:  # not JSON
                    await bench.hub.send(ws, ErrorOut(message="expected a JSON object"))
                    continue
                bench.bus.publish(Event(ev.UI, msg, client=ws))
        except WebSocketDisconnect:
            pass
        finally:
            bench.disconnect(ws)

    return app


app = create_app()
