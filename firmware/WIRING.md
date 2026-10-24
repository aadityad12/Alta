# Probe pod wiring (#5)

The pod = Uno R3 + the **kit** 830-point breadboard ("pod board"), taped side by side on cardboard until the dock (#37) is printed. Hole names use the same scheme as the lab board (`docs/CONTRACTS.md` §4). Diagram: `docs/visuals/pod-wiring-v1.html`.

⚠️ **Power only from the laptop's USB.** Never connect the kit's 6×AA (9 V) pack to anything the probes can touch. Everything stays ≤ 5 V. No soldering.

## Parts
Uno R3 + USB cable · kit breadboard · 4 × 10 kΩ (brown-black-orange) · 3 × 220 Ω (red-red-brown) · 4-leg tactile button · RGB LED · jumpers: 4 **long** ones for the probes (yellow, blue, green, white; tape flags Y/B/G/W if colors are missing), 1 red + 1 black for lab power, ~10 short ones.

## 1 · Pod board power
| from (Uno) | to (pod board) | wire |
|---|---|---|
| 5V | `rail:a+` | red |
| GND | `rail:a-` | black |

## 2 · Probe channels
Each channel: Uno analog pin → row (a side) → **10 kΩ across the center gap** → the probe wire leaves from the j side.

| probe | Uno pin | jumper into | 10 kΩ | probe wire starts at |
|---|---|---|---|---|
| **Y** yellow | A0 | `3a` | `3e` ↔ `3f` | `3j` |
| **B** blue | A1 | `6a` | `6e` ↔ `6f` | `6j` |
| **G** green | A2 | `9a` | `9e` ↔ `9f` | `9j` |
| **W** white | A3 | `12a` | `12e` ↔ `12f` | `12j` |

The 10 kΩ is a safety resistor. If a probe touches something it shouldn't, it limits the current into the Uno pin to under 0.5 mA, and the reading barely changes (the ADC draws almost nothing).

## 3 · Talk button
Straddle the center gap with legs in `20e`, `22e`, `20f`, `22f`. Use **diagonal** legs (diagonal legs are always the switched pair, whichever way the button is rotated):

| from | to |
|---|---|
| Uno D2 | `20j` (button leg at `20f`) |
| `22a` (button leg at `22e`) | `rail:a-` (GND) |

No resistor: the firmware uses the internal pull-up, so pressed = 0.

## 4 · Status RGB LED
**First find its type** (the longest leg is the shared one): long leg to GND, one short leg through a 220 Ω to 5 V. If it lights, it's **common-cathode**. If not, try long leg to 5 V and a short leg through 220 Ω to GND. If that lights, it's **common-anode**.

Then place it with legs in `26b` `27b` `28b` `29b`, the **long leg in `27b`**. The usual leg order is R, common, G, B, so the single leg on one side of the long leg is red.

| LED leg | 220 Ω | jumper |
|---|---|---|
| R (`26b`) | `26e` ↔ `26f` | `26j` → Uno **D9** |
| G (`28b`) | `28e` ↔ `28f` | `28j` → Uno **D10** |
| B (`29b`) | `29e` ↔ `29f` | `29j` → Uno **D11** |
| common (`27b`) | none | `27a` → `rail:a-` if common-cathode, `rail:a+` if common-anode |

If the colors come out in the wrong order, leave the wiring alone; we remap the pins in firmware (#8).

## 5 · Power to the lab board
| from (pod board) | to (lab board) | wire |
|---|---|---|
| `rail:a+` | `rail:a+` | red |
| `rail:a-` | `rail:a-` | black |

The pod powers the lab circuits, so the probes always share their ground.

## 6 · Sanity test
```sh
uv run firmware/sanity/check_pod.py --upload
```
This flashes `firmware/sanity/sanity.ino` (needs `arduino-cli` with the `arduino:avr` core: `brew install arduino-cli && arduino-cli core install arduino:avr`). Then it walks you through:
- all probes on the − rail: each must read ≤ 10 (≈ 0)
- all probes on the + rail: each must read ≥ 1013 (≈ 1023)
- the button: 0 while held, 1 when released
- the LED: red → green → blue → off; it also tells you common-anode vs common-cathode

It ends with a summary to paste into #5. Then take a top-down photo → `docs/visuals/pod-wiring-photo.jpg`.
