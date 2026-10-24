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
from .bus import Event
from .hub import Bench
from .labs import load_labs
from .protocol import BadMessage, ErrorOut, parse_inbound

REPO_ROOT = Path(__file__).resolve().parents[2]
LABS_DIR = REPO_ROOT / "labs"
DEMO_LABS_DIR = Path(__file__).resolve().parent / "demo_labs"

load_dotenv(REPO_ROOT / ".env")
logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s: %(message)s")
log = logging.getLogger("bench")


def create_app(*, demo_ui: bool | None = None, labs_dir: Path = LABS_DIR) -> FastAPI:
    if demo_ui is None:
        demo_ui = os.environ.get("BENCH_DEMO_UI") == "1"
    roots = [labs_dir, DEMO_LABS_DIR] if demo_ui else [labs_dir]
    bench = Bench(load_labs(*roots))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        log.info("labs: %s%s", ", ".join(bench.labs) or "none", " (demo UI mode)" if demo_ui else "")
        tasks = [asyncio.create_task(bench.run())]
        if demo_ui:
            from .demo import run_demo
            tasks.append(asyncio.create_task(run_demo(bench)))
        yield
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(title="Bench", lifespan=lifespan)
    app.state.bench = bench

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
