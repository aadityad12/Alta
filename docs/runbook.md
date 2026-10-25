# ALTA demo runbook

How to get ALTA from a powered-off laptop to demo-ready, keep it running at the judging table, and recover when something breaks. #45 asks for cold start in **under 2 minutes**; #46 asks for table setup from a packed bag in **under 10**.

**The demo laptop** is whichever laptop the pod is plugged into. The server has to run on that laptop, because it reads the pod over USB and plays ALTA's voice through that laptop's speaker. Any laptop works if it has gone through [one-time setup](#one-time-setup-on-a-new-laptop) once.

> Until the student screen (#28–#30) is in `web/`, two dev pages stand in for it: **`http://localhost:8000/brain`** (transcript, gauges, talk button, New student) and **`http://localhost:5173/dev/board`** (camera, calibration, overlays). Once the student screen lands, open `http://localhost:5173` instead of `/brain`.

## Cold start (target < 2 min)

From the repo root:

1. [ ] Power on, plug in the charger, and join the network (hotspot if the venue Wi-Fi is bad).
2. [ ] Plug in the pod's USB cable. Put the phone on the stand, looking straight down.
3. [ ] Check that everything ALTA needs is ready (~5 s):
   ```sh
   cd server && uv run python -m bench.preflight --hear && cd ..
   ```
   Every line should be ✓, ending in **Ready for the demo.** You hear "ALTA is ready." Fix any ✗ with the line under it, then run it again.
4. [ ] Start ALTA: `scripts/dev.sh`. Leave this terminal open; Ctrl-C stops everything.
5. [ ] In the browser:
   - `http://localhost:5173/dev/board`: pick the phone camera, calibrate (click the 4 corner holes it asks for), choose **Lab 1**, switch **Live** on.
   - `http://localhost:8000/brain`: Lab 1 is loaded and the state is `idle`.
6. [ ] Quick check: touch the yellow probe to the 5 V rail, and its gauge reads about 5 V. Hold the pod button, say "Can you hear me?", and ALTA answers out loud.

## Judging day: table setup (#46)

1. [ ] Unpack: laptop + charger, pod in its dock + USB cable, lab board + fault kit, phone + stand + tape, hotspot phone.
2. [ ] Do the [cold start](#cold-start-target--2-min).
3. [ ] Stage the first fault (Lab 1, **LED reversed**: long leg into 13d, short leg into 10d). The LED is dark. Probes out.
4. [ ] Keep the volume reasonable: the table is shared.
5. [ ] Open the backup video (#40) in a window behind the browser. It plays offline.

### Between judges (< 15 s)

1. [ ] **New student**: the button on `/brain` (`N` on the student screen). This clears the conversation and the highlights.
2. [ ] Pull all probes out.
3. [ ] Put the fault back: flip the LED back into the reversed position.

Don't restart the server between judges. It keeps the prompt cache and the voice connection warm, so the first question is fast.

### The demo, in one line each

1. The student holds the pod button: "My LED won't light."
2. ALTA asks for the yellow probe at row 10. Row 10 glows on the board feed.
3. The student plugs it in. ALTA reacts on its own (no button): row 10 is at 5 V, so what does that say about the LED?
4. The student flips the LED. ALTA confirms on its own: about 2 volts now, it's lit.

Other faults in the kit, if a judge wants another round (`labs/lab1-led/lab.yaml`): 10 kΩ instead of 220 Ω, LED leg one row off, ground wire missing.

## If something goes wrong

The screen shows a banner for the pod, AI and voice parts (#31), and the server keeps running through all of these. **Two failed tries in front of a judge → play the backup video** and keep talking over it.

| What you see | What to do |
|---|---|
| Banner "Plug the pod's USB cable back in" / gauges frozen | Replug the USB. It reconnects by itself in under 2 s. Still nothing: another program has the port (close `live.py`, `bringup.py`, Arduino serial monitor) |
| The log repeats `pod connection lost: no data within 3 s of opening` (the port is there, but the pod is silent) | The Uno's USB chip is stuck. Unplug the USB for **10 s**, then plug it back in. Its L LED flickering fast means the firmware itself is fine |
| Banner "ALTA can't reach its brain" / ALTA says "Sorry, my brain glitched" | Internet. Switch to the hotspot; the next question works, no restart needed |
| Banner "ALTA's voice service isn't responding" | Internet again (Cartesia). Captions still appear; type the question instead of talking (`/` on the student screen, the text box on `/brain`) |
| "I didn't catch that" | Talk after the LED turns green, closer to the laptop. Crowd noise: type instead |
| No sound, but captions appear | Laptop volume / output device. `SPEAKER_DEVICE` in `.env` (`uv run python -m bench.voice_out --list-devices`) |
| ALTA ignores the probe you plugged in | It only watches the probe and hole it asked for. Check the gauge shows an expected band, and that the probe is in that exact hole |
| "the camera didn't answer" in the feed | `/dev/board` must be open, calibrated and in **Live** mode. Only one tab should be in Live mode |
| Overlays land on the wrong rows (stand got bumped) | `/dev/board` → calibrate again (4 clicks, < 20 s) |
| Replies take > 4 s | Slow network, or not in fast mode: the server's start-up log must say `agent model: claude-opus-5-5 (fast mode)` |
| The camera page shows `Failed to resolve import "yaml"` (or any package) | Old web install. `cd web && npm install`, then restart `scripts/dev.sh` (it now reinstalls by itself when `package.json` changes) |
| Port 8000 / 5173 in use when starting | An old `scripts/dev.sh` is still running: find its terminal and Ctrl-C it |
| Anything else, and it won't recover | Ctrl-C `scripts/dev.sh`, run it again (~10 s), New student. Then the backup video if needed |

## One-time setup on a new laptop

Do this once per laptop, well before the demo, with internet.

1. [ ] Install the tools: `brew install uv node`. You also need git.
2. [ ] `git clone https://github.com/aadityad12/CalHacks13.0 && cd CalHacks13.0`
3. [ ] `cp .env.example .env` and fill it in, with no quotes around values:
   ```
   ANTHROPIC_API_KEY=...
   CARTESIA_API_KEY=...
   BENCH_MODEL=claude-opus-5-5
   BENCH_SPEED=fast
   BENCH_VOICE=man          # or woman
   POD_PORT=                # empty = find the Uno by itself
   ```
   Get the keys from a teammate privately. Never commit `.env` or paste the keys in an issue: the repo is public.
4. [ ] Run `scripts/dev.sh` once to install everything, then Ctrl-C it.
5. [ ] Plug in the pod and run `cd server && uv run python -m bench.preflight --hear`. All ✓.
6. [ ] macOS asks for **microphone** and **camera** permission the first time (terminal and browser). Say yes, or the talk button and camera stay silent.

## Before the freeze (#45)

- [ ] Tag the commit we demo: `git tag v1.0-demo && git push --tags`. After that, the demo laptop stays on that tag: `git checkout v1.0-demo`. No `git pull` at the table.
- [ ] Battery: with the charger unplugged, run the demo for 10 minutes and note the battery used. If there's no outlet at the table, that tells us how many runs we get.
