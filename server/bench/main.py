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
from .agent import Agent
from .bus import Event
from .hub import Bench
from .labs import load_labs
from .pod import OFF, PodBridge
from .protocol import BadMessage, ErrorOut, parse_inbound
from .voice_in import MIC_OFF, CartesiaSTT, Mic, VoiceIn, mic_device

REPO_ROOT = Path(__file__).resolve().parents[2]
LABS_DIR = REPO_ROOT / "labs"
DEMO_LABS_DIR = Path(__file__).resolve().parent / "demo_labs"

load_dotenv(REPO_ROOT / ".env")
logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s: %(message)s")
log = logging.getLogger("bench")


def create_app(
    *, demo_ui: bool | None = None, labs_dir: Path = LABS_DIR, pod_port: str | None = None, mic: str | None = None
) -> FastAPI:
    """pod_port: serial device path, "off" for no pod, or None to use POD_PORT / auto-detect.
    mic: input device index or name, "off" for no mic, or None to use MIC_DEVICE (empty = system default)."""
    if demo_ui is None:
        demo_ui = os.environ.get("BENCH_DEMO_UI") == "1"
    if pod_port is None:
        pod_port = os.environ.get("POD_PORT", "").strip() or None
    roots = [labs_dir, DEMO_LABS_DIR] if demo_ui else [labs_dir]
    bench = Bench(load_labs(*roots))
    use_pod = not demo_ui and (pod_port or "").lower() not in OFF
    pod = PodBridge(bench.bus, pod_port) if use_pod else None
    if pod:
        bench.session.pod_command = pod.send
    agent = None if demo_ui else Agent(bench, pod_connected=lambda: bool(pod and pod.connected))
    if mic is None:
        mic = os.environ.get("MIC_DEVICE", "")
    use_mic = agent is not None and mic.strip().lower() not in MIC_OFF

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
        if use_mic:
            bench.voice = open_voice()
        if agent:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                log.warning("ANTHROPIC_API_KEY is not set (.env); Bench will answer with its fallback line")
            log.info("agent model: %s", agent.model)
            tasks.append(asyncio.create_task(agent.run()))
        yield
        if pod:
            pod.stop()
        if bench.voice:
            bench.voice.mic.close()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(title="Bench", lifespan=lifespan)
    app.state.bench = bench
    app.state.pod = pod
    app.state.agent = agent

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
