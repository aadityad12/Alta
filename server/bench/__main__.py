"""Run the server: `uv run python -m bench [--demo-ui] [--voice man|woman] [--port 8000] [--no-reload]`."""

import argparse
import os
from pathlib import Path

import uvicorn


def main() -> None:
    p = argparse.ArgumentParser(prog="bench")
    p.add_argument("--demo-ui", action="store_true", help="no pod, no keys: fake probes, overlays, captions, states")
    p.add_argument("--voice", choices=("man", "woman"), help="ALTA's voice (default: BENCH_VOICE from .env, else man)")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--no-reload", action="store_true")
    args = p.parse_args()

    if args.demo_ui:
        os.environ["BENCH_DEMO_UI"] = "1"  # env survives into uvicorn's reload worker; argv doesn't
    if args.voice:
        os.environ["BENCH_VOICE"] = args.voice
    pkg = Path(__file__).resolve().parent
    labs = pkg.parents[1] / "labs"  # reload when a lab file changes too
    uvicorn.run(
        "bench.main:app",
        port=args.port,
        reload=not args.no_reload,
        reload_dirs=[str(pkg)] + ([str(labs)] if labs.is_dir() else []),
        reload_includes=["*.py", "*.yaml", "*.md", "*.svg"],
        loop="asyncio",  # not uvloop: it resolves hosts in libuv, skipping bench.net's IPv4-first fix
    )


if __name__ == "__main__":
    main()
