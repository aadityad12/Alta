# ALTA contracts

> Copied from issue #2, which is the source of truth. To change anything, comment on #2 and tell the team first.

## 1. Repo layout
```
firmware/          bare-metal C for the Uno probe pod (Makefile, src/)
server/            Python 3.11+ (FastAPI) — package `bench/`
  bench/main.py        FastAPI app + /ws hub
  bench/pod.py         serial bridge to the pod
  bench/agent.py       Claude agent loop + tools
  bench/voice_in.py    push-to-talk + Cartesia STT
  bench/voice_out.py   Cartesia TTS playback
  bench/monitor.py     probe-change events
  bench/prompts/       persona + teaching rules (markdown)
  tools/mock_pod.py    fake pod on a virtual serial port
web/               React + Vite + TypeScript (student screen)
  src/board/           overlay engine (calibration, homography, highlights)
labs/<lab_id>/     lab.yaml + manual.md + schematic.svg + scenarios/
cad/               3D-print files (pod dock)
docs/              CONTRACTS.md, visuals/, samples/, measurements.md, stage log
```
Ports: server `http://localhost:8000` (WebSocket at `/ws`), web `http://localhost:5173`.
`.env` (never committed): `ANTHROPIC_API_KEY`, `CARTESIA_API_KEY`, `POD_PORT`, `BENCH_MODEL=claude-opus-5-5`, `CARTESIA_VOICE_ID`, `MIC_DEVICE`.

## 2. Pod → laptop serial protocol
- 115200 baud, 8N1. **One JSON object per line** (`\n`). Integers only (no floats on the AVR).
- Boot line:
```json
{"hello":"bench-pod","fw":"0.1.0","probes":["Y","B","G","W"]}
```
- Sample line, **every 50 ms (20 Hz)**:
```json
{"seq":812,"t":40600,"mv":[5012,1921,-1,3],"lo":[4990,1900,-1,0],"hi":[5030,1940,-1,8],"vcc":4987,"btn":0}
```
| field | meaning |
|---|---|
| `seq` | counter, +1 per line |
| `t` | ms since boot |
| `mv` | average millivolts over the 50 ms window, index 0–3 = Yellow (A0), Blue (A1), Green (A2), White (A3) |
| `lo` / `hi` | min / max millivolts seen in the window (shows flicker and noise) |
| `-1` | probe detected as unplugged (optional feature; until it exists, always send a number) |
| `vcc` | pod supply in mV, measured with the internal 1.1 V reference |
| `btn` | 1 while the talk button is held (debounced) |
- Event line, sent **immediately** on button edges (don't wait for the 50 ms tick):
```json
{"evt":"btn","down":1,"t":40612}
```

## 3. Laptop → pod commands
ASCII lines ending in `\n`:
```
LED IDLE     → off
LED LISTEN   → green
LED THINK    → blue
LED SPEAK    → white
LED ERROR    → red
PING         → {"pong":1,"fw":"0.1.0"}
```
Unknown command → `{"err":"unknown_cmd"}`.

## 4. Breadboard coordinates (830-point board)
- Rows `1`–`63` run along the board. Columns `a`–`e` sit on one side of the center gap, `f`–`j` on the other.
- **Hole:** `"10c"`
- **Strip** (the 5 connected holes of one row-half): `"10:a-e"` or `"10:f-j"`
- **Rail:** `"rail:a+"`, `"rail:a-"` (the rails next to column a), `"rail:j+"`, `"rail:j-"`
- The same strings are used in lab files, overlays, agent tools and the manuals.

## 5. WebSocket API (`ws://localhost:8000/ws`), JSON `{ "type": ..., ... }`
**Server → web**
| type | fields | notes |
|---|---|---|
| `lab` | `lab` (lab.yaml as JSON, plus `manual_md` and `schematic_url`) | on connect and on `select_lab` |
| `probes` | `mv[4]`, `lo[4]`, `hi[4]`, `vcc`, `btn`, `t` | throttled to 10 Hz |
| `expect` | `probe` ("Y"…), `at` ("10c"), `expected_mv`, `tol_mv`, `label` — or `probe` + `clear: true` | ALTA asked for this probe; the UI shows the expected band |
| `overlay` | `mode` ("replace" or "add"), `items: OverlayItem[]` | see below |
| `overlay_clear` | — | |
| `manual` | `step` | scroll/highlight the manual |
| `schematic` | `nets: string[]` | highlight these net ids in the SVG |
| `transcript` | `role` ("student", "bench", "system"), `text`, `final` | captions |
| `state` | `value`: idle, listening, transcribing, thinking, speaking, error; optional `detail` | drives the status indicator |
| `request_frame` | `id` | the agent wants to look at the board |
| `error` | `message` | |
| `health` | `pod`, `ai`, `voice`: each `"ok"`, `"down"` or `"off"` (not set up); `fix`: `{part: one-line fix}` for each part that's down | on connect and on every change. Drives the error banners (#31). Separate from `state`: talking still works while a banner is up |

**`health` example** (Claude unreachable):
```json
{ "type": "health", "pod": "ok", "ai": "down", "voice": "ok", "fix": { "ai": "ALTA can't reach its brain. Check internet / hotspot" } }
```
The screen handles camera-missing and server-down itself (no video track / the `/ws` socket closed).

**OverlayItem**
```json
{ "id": "h1", "kind": "strip", "at": "10:a-e", "style": "probe-Y", "pulse": true }
```
- `kind`: `hole` | `strip` | `rail` | `arrow` (uses `from`, `to`) | `label` (uses `at`, `text`) | `component` (uses `ref`, e.g. "D1"; the engine highlights that part's pins from the lab file)
- `style`: `probe-Y` | `probe-B` | `probe-G` | `probe-W` | `attention` | `good` | `bad`

**Web → server**
| type | fields | notes |
|---|---|---|
| `hello` | `client: "student-screen"` | |
| `select_lab` | `lab_id` | |
| `ptt` | `down: true/false` | on-screen talk button or spacebar |
| `text` | `text` | typed question (fallback when it's too loud) |
| `frame` | `id`, `jpeg_b64`, `w`, `h` | reply to `request_frame`, with row numbers drawn on it |
| `step` | `step` | student moved the manual |
| `reset` | — | new student (between judges) |

## 6. Lab definition (`labs/<lab_id>/lab.yaml`)
```yaml
id: lab1-led
title: "Lab 1 · Light an LED"
supply_mv: 5000
parts:
  - {ref: W1, kind: wire, color: red,   pins: {"1": "rail:a+", "2": "6a"}}
  - {ref: R1, kind: resistor, value_ohm: 220, pins: {"1": "6c", "2": "10c"}}
  - {ref: D1, kind: led, color: red, pins: {anode: "10d", cathode: "13d"}}
  - {ref: W2, kind: wire, color: black, pins: {"1": "13a", "2": "rail:a-"}}
nets:
  - {id: n_5v,        label: "5 V",       holes: ["rail:a+", "6:a-e"],  expected_mv: 5000, tol_mv: 250}
  - {id: n_led_anode, label: "LED anode", holes: ["10:a-e"],            expected_mv: 1900, tol_mv: 300}
  - {id: n_gnd,       label: "Ground",    holes: ["13:a-e", "rail:a-"], expected_mv: 0,    tol_mv: 100}
steps:
  - {n: 1, title: "Power the rails", nets: [n_5v]}
  - {n: 2, title: "Add the resistor", nets: [n_5v]}
  - {n: 3, title: "Add the LED", nets: [n_led_anode, n_gnd]}
faults:
  - id: led_reversed
    name: "LED in backwards"
    how_to_stage: "Flip D1 so the long leg is in row 13"
    symptom: "LED stays dark"
    readings: {n_led_anode: 5000, n_gnd: 0}
    root_cause: "An LED only lets current flow one way. Reversed, no current flows, so the resistor drops nothing."
    hints:
      - "L1 nudge: Let's find where the power stops."
      - "L2 question: If current were flowing, what would the resistor do to the voltage?"
      - "L3 point: Look at the LED's legs in rows 10 and 13. Which one is longer?"
      - "L4 fix: The long leg (anode) goes toward the resistor, in row 10."
verified: false
```
The **net ids** (`n_led_anode`, …) must match the element ids in `schematic.svg`. The manual's step numbers must match `steps`.

## 7. Agent tools (what Claude can call)
| tool | input | what the server does |
|---|---|---|
| `read_probes` | `{}` | returns each probe's mV, lo/hi, unplugged flag, and the hole it was last asked to go to |
| `ask_for_probe` | `{probe, at, expect_net?}` | highlights `at` in that probe's color, sends `expect` to the UI, remembers the request. **ALTA speaks the instruction itself.** |
| `highlight` | `{items: OverlayItem[], mode}` | sends `overlay` |
| `clear_highlights` | `{}` | sends `overlay_clear` |
| `show_manual_step` | `{step}` | sends `manual` |
| `highlight_schematic` | `{nets}` | sends `schematic` |
| `look_at_board` | `{}` | sends `request_frame`, waits ≤2 s, returns the annotated JPEG to Claude |
| `record_diagnosis` | `{fault_id or "unknown", confidence 0–1, evidence, hint_level 1–4, resolved}` | logs it (metrics and the TA dashboard) |

ALTA's **spoken words are its normal text reply**, not a tool. If ALTA has nothing useful to say after an event, it replies exactly `<silent>` and the server stays quiet.
