Bare-metal C firmware for the Uno probe pod (Makefile, src/). Owned by Engineer A.

Pod wiring: `WIRING.md` (#5). Wiring sanity test: `uv run firmware/sanity/check_pod.py --upload`.

## What it does
It reads A0–A3 (Y/B/G/W probes) about 1,200 times a second each. Every 50 ms it prints one JSON line with the mean/min/max in mV, the measured supply (`vcc`) and the talk button. It sends an event line immediately whenever the button changes, and it obeys the `LED …`/`PING` commands. The format is exactly `docs/CONTRACTS.md` §2–3. No Arduino libraries: our own drivers on the ATmega328P registers.

| file | job |
|---|---|
| `src/main.c` | boot (LED self-test, hello), main loop: commands, button events, 50 ms sample lines |
| `src/adc.c` | interrupt-driven ADC: A0→A3 with one throw-away conversion after each mux switch, plus the 1.1 V bandgap every 500 ms for `vcc` |
| `src/uart.c` | 115200 8N1, RX and TX ring buffers on interrupts (printing never stalls the loop) |
| `src/timer.c` | 1 ms Timer0 tick (`timer_millis`), which also drives the button debounce |
| `src/button.c`, `src/led.c` | talk button on D2 (pull-up, 20 ms debounce) · RGB LED on D9/D10/D11 |
| `src/proto.c`, `src/measure.c`, `src/debounce.c` | wire format, mV/vcc maths, debounce: **pure C**, unit-tested on the laptop |

## Build, test, flash
```sh
brew tap osx-cross/avr && brew install avr-gcc avrdude   # or just arduino-cli's copy (the Makefile finds it)
make            # → build/cc/bench.hex   (make LED=ca → build/ca/… for a common-anode LED)
make test       # host unit tests: the exact #2 example lines, command parsing, maths, debounce
make check      # the real bench.elf in simavr ↔ the server's real serial bridge (needs brew install osx-cross/avr/simavr)
make flash      # auto-detects the Uno; or PORT=/dev/cu.usbmodemXXXX (BAUD=57600 for old-bootloader clones)
make monitor    # serial monitor: type PING or LED THINK
```
Close the server and any serial monitor before flashing (the port can only be open once).

## Without hardware: the simulator
`make sim` runs the real firmware in simavr. Its UART appears at `/tmp/bench-pod-sim` (so `POD_PORT=/tmp/bench-pod-sim scripts/dev.sh` works). Type `Y 1900`, `vcc 4700`, `btn`, `bounce`, `reset` or `status` to drive it; the LED colors are printed as they change.

`make check` runs 25 checks against the server's `PodBridge`, plus a 60 s soak (`LONG=10 make check` for a quick run):
- **#6:** `hello`
- **#7:** §2 shape, 20 Hz, and the test matrix: GND, 5 V, 3.3 V, divider, and a supply that sags while readings stay right
- **#8:** self-test colors, all five LED commands, `err`, the button (~19 ms latency, a bouncy press gives exactly one down + up, PTT), reset recovery

## Bring-up on the real pod (~10 min)
1. Wire it (`WIRING.md`). Optional: `uv run sanity/check_pod.py --upload` checks the wiring with a plain Arduino sketch and tells you the LED type.
2. `make flash` (add `LED=ca` if the LED is common-anode).
3. `uv run bringup.py`: guided #7 test matrix, LED colors, PING, button and a 60 s soak. It ends with a summary to paste into #6/#7/#8.
