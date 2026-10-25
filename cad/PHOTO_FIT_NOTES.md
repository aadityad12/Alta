# Photo and source cross-check · 2026-10-24

The user supplied a 591 × 1280 px image showing an Uno R3-compatible board
and an unmarked white mini breadboard. The mini has 17 columns, two groups
of five holes per column, and no power rails: 170 holes total.

## Three cross-checks

1. **Manufacturer listings:** Makerfabs 45 × 35 × 8.5 mm; SparkFun PRT-12043
   47 × 35 × 10 mm; BusBoard BB170 45.7 × 35.6 × 9.4 mm. Links are in README.
   These establish a size family, not this board's manufacturer.
2. **Hole pitch:** assuming standard 2.54 mm pitch, 16 intervals span
   40.64 mm. The first visible row spans about 185 px; the outside length
   is about 207 px, suggesting roughly 45–46 mm. The approximately 159 px
   outside width is consistent with roughly 35 mm. Pixel selections are
   approximate, not a calibrated measurement. Height/hidden tabs are unknown.
3. **Uno reference:** Arduino publishes a 68.6 × 53.4 mm PCB. In the photo
   it is about 300 × 230 px and the mini about 207 × 159 px. Simple ratios
   suggest about 47 × 37 mm. The difference from the hole-pitch estimate
   reflects perspective, differing elevations and approximate edge selection.
   This confirms the size class, not submillimeter accuracy.

## Design consequence

The mini mounting outline has a **54.8 × 42.8 mm clear interior**, exceeding
the largest cited footprint by 7.8 × 7.2 mm in total. Center the board and
retain it with mounting tape. The Uno has no matching pegs or tight connector
opening. The open top does not constrain board/component height. The model
therefore avoids relying on the exact body size, tab dimensions, mounting
holes, or backing thickness. **Physical fit remains unverified.**

## Later ruler photos: basis of the current STL

The user then supplied three photos showing the width, length and height
against a centimeter ruler. The first two do not start the board exactly at
zero: subtract the two edge readings rather than reading just the far edge.

- Short side: near edge slightly before zero, far edge around 3.5 cm; total
  approximately **37 mm**, allowing for perspective.
- Long side: one edge about 2 mm beyond zero, the other around 4.5–4.6 cm;
  total approximately **47–48 mm**.
- Height: bottom near zero and top near the 1 cm mark, including backing;
  approximately **10 mm**.

Use **48 × 38 × 11 mm as a conservative design envelope**. These are rounded
engineering allowances, not exact measurements. The clear mount remains
54.8 × 42.8 mm, giving 3.4 mm lengthwise and 2.4 mm widthwise clearance per
side beyond that envelope. The lack of a lid makes height noncritical.
Earlier hole-pitch and catalog estimates above are retained as cross-checks;
the ruler photos now take precedence. No further exact measurement is needed
for this loose tape-mounted design, though physical fit is still untested.
