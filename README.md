# Bench

A voice-driven lab TA that **sees** the breadboard (phone camera), **measures** it (probe pod), and **walks the student to the fault** like a real TA, without handing over the answer. Built at Cal Hacks 13.0.

## How to run (dev)

Needs [uv](https://docs.astral.sh/uv/) and Node.js 20+.

```sh
cp .env.example .env   # fill in keys; never commit .env
scripts/dev.sh
```

- Server: http://localhost:8000 (`/health` → `{"ok": true}`, WebSocket at `/ws`)
- Web: http://localhost:5173

No pod or API keys yet? `scripts/dev.sh --demo-ui` runs the server on fake data: probes, overlays, captions and states loop on a demo copy of Lab 1.

Server tests: `cd server && uv run pytest`

## Docs

- `docs/CONTRACTS.md`: serial protocol, WebSocket API, lab schema, agent tools (source of truth is issue #2)
- `docs/visuals/`: plan and flow diagrams (open in a browser)
