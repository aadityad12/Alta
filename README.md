# ALTA

**ALTA (AI Lab Teaching Assistant)** is a voice-driven lab TA that **sees** the breadboard (phone camera), **measures** it (probe pod), and **walks the student to the fault** like a real TA, without handing over the answer. Built at Cal Hacks 13.0.

## How to run (dev)

Needs [uv](https://docs.astral.sh/uv/) and Node.js 20+.

```sh
cp .env.example .env   # fill in keys; never commit .env
scripts/dev.sh
```

- Server: http://localhost:8000 (`/health` → `{"ok": true}`, WebSocket at `/ws`)
- Web: http://localhost:5173

No pod or API keys yet? `scripts/dev.sh --demo-ui` runs the server on fake data: probes, overlays, captions and states loop on a demo copy of Lab 1.

No pod on the desk? Run the mock pod (#9) in a second terminal: `cd server && uv run python tools/mock_pod.py`, then start the server with `POD_PORT=/tmp/bench-pod scripts/dev.sh` (or put that in `.env`). Type `help` in the mock for commands like `Y 10c`, `fault led_reversed`, `btn`.

Talk to ALTA by typing (no voice or browser; needs `ANTHROPIC_API_KEY` in `.env`):

```sh
cd server && uv run python -m bench.cli --lab lab1-led --pod off   # or --pod /tmp/bench-pod
```

Check the mic and speech-to-text: `cd server && uv run python -m bench.voice_in --list-devices`, then `--test 4` (records 4 s and prints the transcript). Pick a mic with `MIC_DEVICE` in `.env`.

Hear ALTA's voice: `cd server && uv run python -m bench.voice_out "Row 10 reads 1.92 V."` (prints the time to first audio). Pick the voice and speaker with `CARTESIA_VOICE_ID`, `BENCH_VOICE_SPEED` and `SPEAKER_DEVICE` in `.env`.

Every student session is logged to `recordings/<time>-<lab>.jsonl` (gitignored; `BENCH_RECORD_DIR=off` turns it off), and each spoken turn's latency is printed in the server log. Summarize the logs: `cd server && uv run python -m bench.metrics ../recordings/*.jsonl` (turns, probes, hint level, time to fix, latency).

Server tests: `cd server && uv run pytest`

## Docs

- `docs/CONTRACTS.md`: serial protocol, WebSocket API, lab schema, agent tools (source of truth is issue #2)
- `docs/visuals/`: plan and flow diagrams (open in a browser)
