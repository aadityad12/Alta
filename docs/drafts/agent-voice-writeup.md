# Drafts: the agent and voice parts, for the README, Devpost and Q&A

Engineer B's raw material for Designer 2 (#42 README, #41 Devpost, #39 Q&A). Copy, cut and reword freely. Every number here comes from `docs/measurements.md` (Sat 24 Oct, Opus 5.5 fast mode) unless it says otherwise. Hardware and pod numbers (#10) are Engineer A's and aren't here.

---

## 1. README sections (#42)

### Agent: how ALTA thinks

ALTA is Claude Opus 5.5 with eight tools that act on the real bench. It never just guesses from what the student says: it **measures before it diagnoses**.

| tool | what it does |
|---|---|
| `ask_for_probe` | asks for one probe at one hole, highlights that hole on the board feed and sets the expected voltage band on the gauge |
| `read_probes` | the four probes' live voltages from the pod |
| `look_at_board` | a photo from the overhead camera with row numbers and column letters drawn on it. Used for *where* things are, never for voltages |
| `highlight` / `clear_highlights` | draws on the live board feed: holes, strips, rails, parts |
| `highlight_schematic` | highlights a net on the lab's schematic |
| `show_manual_step` | opens the matching step of the student's manual |
| `record_diagnosis` | logs what ALTA thinks is wrong and which hint level it used |

**Teaching policy** (`server/bench/prompts/teaching.md`):
- **Hint ladder.** Nudge → question → point at the spot → the fix. ALTA moves up one level only when the current one didn't work. It gives the fix only after the student has asked twice or failed three times.
- **Measure first.** No fault is named without a reading that supports it. When the probes and the camera disagree, ALTA trusts the probes and measures again.
- **Confirm the fix.** After the student fixes something, ALTA checks it with a measurement before it celebrates, and the praise names the reading ("Row 10 is at about 2 volts now, so current is flowing").
- **Short.** At most two sentences and one question, because everything ALTA says is spoken.

**It reacts without being asked.** A probe monitor watches the probe ALTA asked for. When that probe settles at the right hole, or its reading jumps into the expected range because the student just fixed the circuit, ALTA gets an event and responds, with no button press. Readings count only once they hold steady for 500 ms, so wiggling a probe doesn't set it off.

**Every lab is a data file.** `labs/<lab>/lab.yaml` holds the parts and their exact holes, the nets with expected voltages, the manual, and each known fault with how it reads and its hint ladder. Adding a lab means writing that file, not changing code.

### Where it could go wrong, and what we do about it

| risk | what ALTA does |
|---|---|
| Claude names the wrong fault | It can't name one without a measurement, and it confirms every fix with a new one. In 42 test runs it named the right fault every time |
| The camera misreads the board | Photos are only for *where* (which row, which way round). Voltages always come from the probes, and if the two disagree, the probes win |
| ALTA gives the answer away | The hint ladder caps it, and our scenario tests grade every reply with a second model. In 41 / 42 runs it never gave the fix early, and no run needed the full answer |
| A noisy room | Push-to-talk on the pod's button plus a typed fallback on the screen |
| The internet drops | The screen shows a banner with the fix ("check internet / hotspot"), ALTA says a short fallback line, and it recovers on the next question without a restart |
| The pod gets unplugged | It reconnects by itself in under 2 s, and the status LED comes back in the right color |
| Claude refuses or goes off topic | The server-side refusal fallback plus a prompt rule that steers back to the lab |

### Voice: which Cartesia features we used and why

- **Sonic 3.5 TTS over one warm WebSocket.** The connection opens at startup, so the first reply doesn't pay for the handshake.
- **Streaming input with contexts.** Claude's reply goes to Cartesia sentence by sentence *while Claude is still writing it*, in one context per utterance, with `max_buffer_delay_ms=0`, so each sentence starts playing at once. That's most of why ALTA starts talking about 1.6–1.9 s after the student lets go of the button.
- **Raw PCM (16-bit, 24 kHz)** played straight to the speaker as it arrives, with no file in between.
- **Context cancel for barge-in.** When the student presses the button while ALTA is talking, the context is cancelled and the speaker goes silent at once.
- **`generation_config`** for voice speed and emotion, set before a session.
- **Two voices, picked by ear** from Cartesia's emotion-responsive voices: Gavin (man, the default) or Maya (woman), picked before a session.
- **Ink-Whisper STT** on each push-to-talk clip. The median transcript arrives 0.22–0.27 s after the button is released.
- **Our own text normalizer** before TTS: "1.92 V" is spoken as "about 1.9 volts", "10 kΩ" as "10 kilohms", "ALTA" as the word "Alta".

### Measurements (agent and voice)

| | median | p90 |
|---|---|---|
| Button released → transcript | 0.22–0.27 s | 0.23–0.53 s |
| Button released → ALTA's answer starts playing (Opus fast) | **1.61–1.88 s** | 2.59–3.78 s |
| Button released → first sound, counting the filler line ("Mm, let me check.") | 1.61–1.73 s | 1.84–2.06 s |

Teaching quality: 7 faults across Lab 1 and Lab 2, 3 runs each, against a scripted student and the mock pod's voltage model. ALTA:
- named the right fault in **42 / 42** runs and confirmed the fix with a measurement in **41 / 42**;
- needed a median of **2 probe placements** and 5–6 turns per fault.

The biggest speed-up came from changing the order: ALTA writes its spoken reply *before* its tool calls, in the same response. That cut the time to Claude's first text from 4.7 s to 1.9 s (1.1 s with fast mode).

### Setup & run

```sh
brew install uv node
git clone https://github.com/aadityad12/CalHacks13.0 && cd CalHacks13.0
cp .env.example .env        # add ANTHROPIC_API_KEY and CARTESIA_API_KEY
cd server && uv run python -m bench.preflight --hear && cd ..   # checks everything, ~5 s
scripts/dev.sh              # server on :8000, web on :5173
```

No pod or keys? `scripts/dev.sh --demo-ui` runs the screen on fake data. Full steps, and what to do when something breaks: `docs/runbook.md`.

### Known limitations (agent and voice)

- **Needs the internet.** Claude and Cartesia run in the cloud. With no connection, the screen says so and the student can't get help until it's back.
- **Fast mode is a research preview** with its own rate limit. Without it, standard Opus answers in about 2.4–3 s, and the filler line keeps the silence under ~2.3 s.
- **Push-to-talk, English only.** The student holds a button to talk; there's no wake word.
- **One station per laptop.** The TA dashboard (`/ta`) shows the live station plus five replayed ones; a room of real stations would need a shared server.
- **Labs are hand-written.** Each lab needs its `lab.yaml` with exact holes and expected voltages, written and verified by measuring.
- **Our tests use a scripted student.** It acts on a hint straight away; a real student may need more turns. It also exposed one weak spot: in Lab 2, when the probe is in the wrong row, ALTA sometimes says where to move it one hint level too early.
- **The camera only locates parts.** ALTA can't read resistor color bands or LED brightness from the photo, and doesn't try to.

### Privacy

- No audio is kept. Each clip is sent to Cartesia to transcribe and then dropped (unless someone sets `BENCH_CLIP_DIR` to debug the mic; it's off by default).
- Photos are only taken when ALTA asks to look, at most 1–3 per turn, and only of the bench (the camera points straight down). They are sent to Claude and saved locally for debugging; `BENCH_FRAME_DIR=off` turns saving off.
- Each session writes a local log (transcript text + timings) to `recordings/`, which git ignores. `BENCH_RECORD_DIR=off` turns it off. Nothing is uploaded except the API calls themselves.

---

## 2. Devpost (#41)

**How we built it: the agent and voice.** A Python FastAPI server ties the pod, camera, voice and screen together over one WebSocket. Claude Opus 5.5 runs the conversation with eight tools that act on the bench: it asks for a probe at a hole, reads the live voltages, looks at an annotated photo of the board, and draws highlights on the screen. Its teaching rules make it measure before it diagnoses, climb a four-step hint ladder, and confirm every fix with a new reading. A probe monitor lets ALTA react the moment a probe settles or a reading changes, with no button press. Cartesia Sonic 3.5 speaks Claude's reply sentence by sentence while it's still being written, and Ink-Whisper transcribes push-to-talk clips in about a quarter of a second.

**Challenges.** Speed. ALTA used to think, call its tools, and only then write what to say: 4.7 s before the first word. We flipped it, so Claude writes the spoken reply first and the tool calls after it, in the same response. Streaming that text into TTS as it arrives, plus a pre-warmed prompt cache and Opus fast mode, brought it to **1.6–1.9 s from button release to ALTA's voice**. The other challenge was stopping a very capable model from just giving the answer, which is what the hint ladder and the graded scenario tests are for.

**Accomplishments (numbers).**
- The right fault in **42 / 42** test runs, every fix confirmed with a measurement in **41 / 42**.
- ALTA starts talking **1.6–1.9 s** after the student lets go of the button.
- ALTA reacts on its own when a probe settles or the student fixes the circuit, with no button. *(Reaction time on the real pod: from #21 / #44, to come.)*

**What we learned.** Response order matters more than model size for a voice agent: speaking first saved more time than any model swap. And grounding every claim in a measurement is what makes an AI tutor trustworthy enough to put in front of students.

**Built with (agent and voice):** Python, FastAPI, Claude Opus 5.5 (tool use, prompt caching, fast mode, vision), Cartesia Sonic 3.5 + Ink-Whisper, uv, pytest.

---

## 3. Judge Q&A answers (#39, for `docs/qa.md`)

- **Why not just use vision?** A photo can't tell you a voltage. Two circuits can look the same and read completely differently. ALTA uses the camera for *where* things are, and the probes for *what's happening*.
- **What if Claude is wrong?** It can't name a fault without a measurement, and it confirms every fix with a new one. If a reading doesn't fit, it asks whether the probe is in place. In our tests it named the right fault 42 / 42 times.
- **Doesn't it just give students the answer?** No. It climbs a four-step hint ladder and only gives the fix after the student has asked twice or failed three times. In 41 / 42 test runs it never gave the fix early, and no run needed the full answer.
- **Latency?** About 1.6–1.9 s from releasing the button to ALTA's voice (median). A short filler line ("Mm, let me check") covers slower turns, so the silence stays under ~2 s.
- **Why Cartesia?** Streaming input: we send Claude's reply one sentence at a time while it's still being written, and it starts speaking straight away. Ink-Whisper also transcribes a clip in about 0.25 s.
- **Why Claude / Opus?** Tool use that's reliable enough to drive real hardware, plus vision, prompt caching and fast mode. Opus passed all 7 fault scenarios; Sonnet was less consistent and not much faster.
- **What's custom-built (agent side)?** The agent loop, the eight tools, the teaching rules, the probe monitor, the latency work (speak first, streaming TTS, cache pre-warm), and a scenario test suite that grades ALTA's teaching with a second model.
- **Privacy?** No audio is kept. Photos are only taken when ALTA asks to look, only of the bench, and stay on the laptop apart from the Claude call. Session logs are local and can be turned off.
- **Cost?** About 2–3 cents per ALTA reply in fast mode, mostly cached prompt reads. *(The hardware cost per bench is Engineer A's / Designer 2's number.)*
- **How would a real lab adopt it?** A TA writes one `lab.yaml` per lab: parts, holes, expected voltages, common faults. ALTA works from that, so there's no code to change. The TA dashboard (`/ta`) shows which stations are stuck.
