# Mini 170-point pod wiring proposal

The pictured mini board has **17 groups of five holes per side** and **no
power rails**. The existing `firmware/WIRING.md` assumes an 830-point board;
its row 20–29 placements do not apply. This proposal keeps all firmware pins
unchanged. **Built and verified on 2026-10-24:** `check_pod.py` 11/11 and `bringup.py` 25/25 on the real pod (#5–#8).

## Orientation

Hold the board like the photo: long edge and center trench horizontal.
Number the 17 vertical columns **1–17 from left to right**. Within a column,
label the holes top to bottom **a b c d e** above the trench and **f g h i j**
below it. Five holes a–e form one node; f–j form a separate node. Neighboring
numbered columns are separate nodes.

## Probe channels

| Probe | Uno pin → hole | 10 kΩ resistor across trench | Long probe jumper from |
|---|---|---|---|
| Y | A0 → 2a | 2e ↔ 2f | 2j |
| B | A1 → 4a | 4e ↔ 4f | 4j |
| G | A2 → 6a | 6e ↔ 6f | 6j |
| W | A3 → 8a | 8e ↔ 8f | 8j |

## Supply nodes (replacing power rails)

- Uno **5V → 16a**; **16b → lab breadboard positive rail**.
- Uno **GND → 17b**; **17c → lab breadboard ground rail**.
- Row-half **16a–e is 5 V**, row-half **17a–e is ground**.
- Their **f–j halves are separate**, not power buses.

## Talk button

Place the four-leg tactile button across the trench at **15e, 17e, 15f,
17f**. Check its leg spacing fits without force; a different switch footprint
needs a different placement.

- Uno **D2 → 15j**, connecting to the leg in 15f.
- Leg **17e** connects directly to the ground node.
- These are diagonal legs: disconnected when released, connected when pressed.
  Verify with a continuity meter if available.
- The firmware uses D2's internal pull-up; no extra resistor is needed.

## RGB status LED

Identify common-cathode versus common-anode as in `firmware/WIRING.md`.
Assuming its R/common/G/B leg order, place:

- **R = 10b**, **common = 11b**, **G = 12b**, **B = 13b**.
- Three **220 Ω** resistors: **10e ↔ 10f**, **12e ↔ 12f**, **13e ↔ 13f**.
- **10j → D9**, **12j → D10**, **13j → D11**.
- Common-cathode: **11a → 17d (GND)**.
- Common-anode: **11a → 16c (5V)**; use the common-anode firmware build.

There are enough distinct nodes and holes for four probes, seven resistors,
the button, RGB LED, and shared lab power/ground. Actual lead spacing and
wire routing still need checking while assembling. The open dock provides
access to all components.

Power from laptop USB; keep the kit's 9 V battery pack away from the lab board
and probes. Use the existing sanity test after assembly:

```sh
uv run firmware/sanity/check_pod.py --upload
```
