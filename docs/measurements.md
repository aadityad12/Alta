# Measurements

Numbers for the pitch, the README and Devpost. Each section says how it was measured and how to re-run it.

- [Agent latency (#22)](#agent-latency-22)
- [Model comparison (#22)](#model-comparison-22)
- [Scenario tests (#23)](#scenario-tests-23)
- Pod accuracy and latency (#10): Engineer A, to come

## Agent latency (#22)

**Target: median ≤ 2.5 s from releasing the talk button to hearing Bench.** Met with Opus fast mode.

`python -m bench.latency` runs 10 turns through the real pipeline, minus the hardware. macOS `say` speaks the student's line into a 16 kHz WAV (the mic), Cartesia transcribes it, the agent answers against the mock pod's voltages, and Cartesia speaks the reply into a player that notes when the first audio arrives, plus the real speaker's 26 ms. The student is the scripted one from the scenario tests. Lab 1, LED in backwards. Two runs of 10 turns per setting, Sat 24 Oct.

From button release, seconds (median / p90):

| setting | transcript | first Claude text | **reply audio** | first audio (incl. filler) | filler used |
|---|---|---|---|---|---|
| Opus 5.5 low, **fast mode**, run 1 | 0.27 / 0.53 | 1.38 / 2.34 | **1.61 / 2.59** | 1.61 / 2.06 | 4 / 10 |
| Opus 5.5 low, **fast mode**, run 2 | 0.22 / 0.23 | 1.67 / 3.63 | **1.88 / 3.78** | 1.73 / 1.84 | 5 / 10 |
| Opus 5.5 low, normal, run 1 | 0.27 / 0.29 | 2.01 / 3.61 | 2.36 / 3.77 | 1.91 / 2.20 | 7 / 10 |
| Opus 5.5 low, normal, run 2 | 0.24 / 0.35 | 2.51 / 3.78 | 2.97 / 3.94 | 1.94 / 2.27 | 7 / 10 |

"Reply audio" is the first sound of Bench's actual answer. "First audio" includes the filler ("Mm, let me check."), which plays when a student turn has no text after 1.5 s. With the filler, nobody waits more than about 2.3 s in silence in either setting.

**What made the difference: speak first.** Before #22, a typical turn was two Claude requests in a row. The first one thinks and calls `ask_for_probe` / `record_diagnosis` (median 2.7 s, 206 requests). Only the second one writes the reply (median 1.8 s, 186 requests). So Claude's first spoken word came ~4.7 s after the turn started. Now Claude writes the reply first and the tool calls after it, in the same response. The text goes to TTS as it streams, and when every call in the round is a side effect (highlights, `ask_for_probe`, `record_diagnosis`), the turn ends with no second request. Turn start → first Claude text, scenario runs (≈120 turns each):

| | before | speak first |
|---|---|---|
| Opus 5.5 low | 4.71 / 7.21 s | 1.87 / 4.67 s |
| Opus 5.5 low, fast mode | 2.23 / 2.93 s | **1.06 / 2.46 s** |

Also in #22:
- **Cache pre-warm:** a `max_tokens: 0` request on startup, on a new lab, and before the 5-minute cache expires when idle. The first real turn then reads the whole 7.7k-token prefix (tools + system prompt + lab) from cache instead of writing it.
- **`BENCH_SPEED=fast`** turns on Opus fast mode. It costs twice the standard price, which is small at demo volume: about 2–3 cents per turn in fast mode, from the scenario logs (mostly cache reads, plus ~300 output tokens).

Re-run: `cd server && uv run python -m bench.latency [--fast]`. On the real pod and mic, `python -m bench.metrics ../recordings/*.jsonl` reports the same marks from every spoken turn (#44).

## Model comparison (#22)

Same 7 scenarios × 3 runs (below), same prompt, effort `low`. Columns: runs that pass all four rules, scenarios passing ≥ 2 of 3 runs, turn start → first Claude text (median / p90).

| model | runs passed | scenarios ✓ | first text |
|---|---|---|---|
| *before speak-first:* | | | |
| `claude-opus-5-5` | 16 / 21 | 5 / 7 | 4.71 / 7.21 s |
| `claude-sonnet-5-5` | 13 / 21 | 5 / 7 | 3.83 / 5.70 s |
| `claude-opus-5-5`, fast mode | 15 / 21 | 6 / 7 | 2.23 / 2.93 s |
| *speak-first (final):* | | | |
| `claude-opus-5-5` | 18 / 21 | **7 / 7** | 1.87 / 4.67 s |
| `claude-opus-5-5`, fast mode | **19 / 21** | **7 / 7** | **1.06 / 2.46 s** |

**Pick: Opus 5.5, low effort, fast mode.** It teaches as well as standard Opus and responds in half the time. Sonnet 5.5 was less consistent (more long replies, one scenario at 0/3) and not much faster than Opus. Fast mode is a Claude API research preview with its own rate limit. If it's unavailable, standard Opus with the filler still keeps the silence under ~2.3 s.

## Scenario tests (#23)

`python -m bench.scenarios` runs the real agent against every fault in Lab 1 and Lab 2, with a scripted student, the mock pod's voltage model, and the probe monitor on a simulated clock.

The student opens with the fault's symptom, plugs probes where Bench asks, and covers the sensor or shines a light on it when asked. It answers what-do-you-see questions ("which row is the long leg in?") from the fault's `how_to_stage`, using `claude-haiku-5-5`. It fixes the fault once Bench points at it (hint level 3). Otherwise it escalates through canned lines, ending with asking for the answer twice.

Rules checked on every run:
1. **Measure first:** no fault named before a probe reading (from `record_diagnosis`, and in words by the grader).
2. **No fix early:** no reply gives the fix below hint level 3 (graded by `claude-haiku-5-5`).
3. **Confirm the fix:** `resolved` only after the student fixed it, and after a new measurement.
4. **Short replies:** ≤ 2 sentences + ≤ 1 question (3-word interjections like "Nice work!" are free).

Final run, Opus 5.5 low, fast mode, 3 runs per fault:

| lab | fault | pass | 1 measure first | 2 no fix early | 3 confirm the fix | 4 short replies | turns |
|---|---|---|---|---|---|---|---|
| lab1-led | led_reversed | 3/3 ✓ | 3/3 | 3/3 | 3/3 | 3/3 | 6 |
| lab1-led | wrong_resistor_10k | 3/3 ✓ | 3/3 | 3/3 | 3/3 | 3/3 | 4 |
| lab1-led | led_leg_off_by_one | 3/3 ✓ | 3/3 | 3/3 | 3/3 | 3/3 | 6 |
| lab1-led | missing_ground_wire | 3/3 ✓ | 3/3 | 3/3 | 3/3 | 3/3 | 5 |
| lab2-light | wrong_resistor_220 | 3/3 ✓ | 3/3 | 3/3 | 3/3 | 3/3 | 5 |
| lab2-light | output_probe_wrong_row | 2/3 ✓ | 3/3 | 2/3 | 2/3 | 2/3 | 8 |
| lab2-light | parts_swapped | 2/3 ✓ | 2/3 | 3/3 | 3/3 | 3/3 | 8 |

Standard Opus (not fast): 18 / 21 runs, 7 / 7 scenarios.

**Headline numbers (42 final runs, both settings):**
- Bench named the right fault in **42 / 42** runs and confirmed the fix with a measurement in **41 / 42**.
- It needed a median of **2 probe placements** and **5–6 turns** per fault.
- It never gave a fix before hint level 3 in 41 / 42 runs. In all 41 confirmed fixes, a level-3 pointer was the most Bench gave: no run needed a level-4 "here's the answer". *Caveat: the scripted student acts on a level-3 pointer straight away; a real student may need level 4.*

**Where it still slips:**
- **Probe in the wrong row (Lab 2).** Once the student says "my probe is in row 34", Bench sometimes says "move it to row 30" at hint level 1–2, instead of asking where the output is.
- **Opening reply.** Now and then it's 3 sentences.
- **Diagnosing from words alone.** For `parts_swapped`, the student's description ("covering it makes the output go up") was once enough for Bench to name the fault before measuring.

Re-run: `cd server && uv run python -m bench.scenarios [--fast] [--fault <id>] [--runs 3]`. It makes real API calls: about $1.50 for the whole suite, about $3 in fast mode. Transcripts and JSONL logs go to `recordings/scenarios/<time>/`; `python -m bench.metrics` reads the logs.
