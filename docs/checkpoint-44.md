# Checkpoint #44: first run on real hardware

A checklist for the first time the real pod, camera, voice and agent run together. Work top to bottom. Tick boxes in the issues as you go and paste the numbers into each issue.

You don't need the finished student screen (#28–#30) for this. Two dev pages stand in for it:
- **`http://localhost:8000/brain`** (server): state, transcript, probe gauges, expected band, ALTA's highlights, and a live feed of every tool call with timings. The talk button is here too.
- **`http://localhost:5173/dev/board`** (web, Engineer A's #11 page): the live camera with calibration and overlays. In **Live** mode it answers ALTA's camera requests (`look_at_board`).

Both can be open at once. In `/brain`, leave **"Answer ALTA's camera requests with this photo"** unchecked, so the real camera answers.

## 0. Before you start (~10 min)

- [ ] `git pull` on `main`.
- [ ] `.env` (copy from `.env.example`), with no quotes around values:
  ```
  ANTHROPIC_API_KEY=...
  CARTESIA_API_KEY=...
  BENCH_MODEL=claude-opus-5-5
  BENCH_SPEED=fast            # replies start in ~1.6–1.9 s instead of ~2.4–3 s
  POD_PORT=                   # empty = auto-detect the Uno
  MIC_DEVICE=                 # empty = default mic
  SPEAKER_DEVICE=             # empty = default speaker
  ```
- [ ] Pod firmware flashed and checked by Engineer A (`cd firmware && make flash`, then `uv run bringup.py`). **Close `bringup.py` and any serial monitor before starting the server.** The port can only be open once.
- [ ] Lab 1 built correctly (manual `labs/lab1-led/manual.md`): red wire 5 V rail → 5a, 220 Ω resistor 5c–15c, LED anode (long leg) 15e / cathode 20e, black wire 20a → ground rail. The LED lights.
- [ ] Pod's red/black leads on the board's 5 V and ground rails. Probes free (not plugged in).
- [ ] Phone on the stand, looking straight down, and showing as a camera on the laptop (Continuity Camera).

## 1. Start everything

```sh
scripts/dev.sh          # server :8000 + web :5173; Ctrl-C stops both
```

- [ ] The server log shows `pod port open: /dev/cu.usbmodem…`, then `pod says hello: fw …` and `pod connected`. If it shows `no pod found`, check the USB cable, close other serial programs, or set `POD_PORT=/dev/cu.usbmodemXXXX` (`ls /dev/cu.usbmodem*`).
- [ ] The log also shows `mic: …`, `speaker: …` and `agent model: claude-opus-5-5`.
- [ ] Open `http://localhost:8000/brain`: Lab 1 is loaded, state `idle`, the four gauges move when you touch a probe to the 5 V rail.
- [ ] Open `http://localhost:5173/dev/board`: pick the phone camera, calibrate (click the 4 corner holes it asks for), choose **Lab 1**, switch **Live** on. The page says `live: connected`.

## 2. #16 · Pod bridge on the real pod (~5 min)

- [ ] **Replug:** unplug the pod's USB, wait 3 s, plug it back. The log shows `pod disconnected`, then `pod connected` again **within 2 s**, and `/brain` shows the error state, then `idle`. Gauges move again.
- [ ] **LED follows ALTA:** hold the pod button → green (listening). Release → blue (thinking), white (speaking), off (idle). Unplug the pod → it comes back in the right color.
- [ ] **Button starts listening:** holding the pod button puts `/brain` in `listening`, and releasing it gives a transcript.

Paste into #16: the replug time and "LED + button OK", or what went wrong.

## 3. #21 · ALTA reacts to probes by itself (~10 min)

Stage the fault: **flip the LED** (long leg into 20e, short leg into 15e). The LED goes dark.

- [ ] Hold the pod button: "My LED won't light." ALTA asks for a probe (usually yellow, row 10).
- [ ] Plug that probe in **without pressing anything**. ALTA responds **within ~2 s** of the probe settling. The `/brain` feed shows **probe monitor**, then **Claude is given a probe event**, then **ALTA says**. It mentions about 5 volts and asks a guiding question.
- [ ] Leave the probe in. Flip the LED back. ALTA **confirms on its own** ("about 2 volts"), with no button press.
- [ ] Do it **5 times**. ALTA never responds twice to one plug-in or one fix. Wiggling the probe in the same hole doesn't trigger anything.

Paste into #21: probe-settled → reply time (from the `/brain` feed), the auto-confirm result, and double reactions out of 5.

## 4. #20 · ALTA looks at the board (~10 min)

`/dev/board` must be in **Live** mode with the camera calibrated.

- [ ] Ask: "Can you look at my board? Which way round is the LED?" The `/brain` feed shows **Claude calls look_at_board** with its result, and `/dev/board` shows the frame it sent (with row numbers drawn on it).
- [ ] Try it **5 times** with different questions (is there a part in row 10, which row is the black wire in, is the LED backwards). Write down for each: right / wrong / "couldn't tell".
- [ ] ALTA still uses the probes for voltages. It never reads a voltage or LED brightness off the photo.

Paste into #20: the 5 results. If ALTA misreads rows, say which (that tells us whether the fix is in the prompt or the calibration).

## 5. #44 · The end-to-end run (do it 3 times)

Start each run from a clean state: in `/brain`, press **New student** (reset). Fault staged (LED reversed), probes out.

1. [ ] Hold the pod button: "My LED won't light." The transcript appears. **Start the timer at the button press.**
2. [ ] ALTA asks for the **yellow probe at row 10**: row 10 glows yellow on the live feed (`/dev/board`), the gauge shows the expected band, and the schematic highlights the LED anode.
3. [ ] Plug in the probe: ALTA reacts **without** a button press, mentions about 5 V, and asks a guiding question.
4. [ ] Flip the LED: ALTA **confirms on its own** ("about 2 volts"). **Stop the timer.**
5. [ ] Time: ____ s

The schematic highlight in step 2 needs Designer 1's screen (#29). Until it exists, check that the `/brain` feed shows `highlight_schematic` with `n_led_anode`.

- [ ] 3 successful runs in a row, with the 3 times posted in #44
- [ ] Film one good run (phone or screen recording) and post it in #44. It's also raw material for the demo video (#40).
- [ ] Every problem filed as an issue labeled `bug` + the owner's role label
- [ ] Go / no-go on stretch work (#12, #13, #24): only if this passed 3/3

## Latency numbers for the pitch

After the runs:

```sh
cd server && uv run python -m bench.metrics ../recordings/*.jsonl
```

This prints the median time from button release to the transcript and to ALTA's first audio, from the real pod and mic. Paste the table into #44 (and #10 if it helps the pitch).

## If something goes wrong

| What you see | Try |
|---|---|
| `no pod found` | USB cable (some are power-only), close `bringup.py` / serial monitors, `POD_PORT=/dev/cu.usbmodemXXXX` |
| Gauges stuck at one value | Probe not touching metal; check the pod's ground lead is on the board's ground rail |
| Button does nothing | `/brain` state must be `idle` first; check the log for `talk button tap … ignored` (hold it longer than 0.3 s) |
| "I didn't catch that" | Speak after the LED turns green; check `MIC_DEVICE` (`uv run python -m bench.voice_in --list-devices`) |
| No sound | `SPEAKER_DEVICE`; captions still appear in `/brain` |
| ALTA ignores the plugged probe | It only watches the probe it asked for, at the hole it asked for. Check `/brain` shows the expected band for that probe |
| `look_at_board` says the camera didn't answer | `/dev/board` must be in Live mode and calibrated; only one page should answer frames |
| Replies take > 4 s | `BENCH_SPEED=fast` set? Hotspot/Wi-Fi slow? The `/brain` feed shows where the time goes |
