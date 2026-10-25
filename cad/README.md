# Bench probe pod dock · issue #37

**Use `pod_dock.stl`.** It holds the pictured Uno R3 and **170-point mini
breadboard**, using tape retention and generous clearance based on the ruler photos. The earlier
`pod_dock_DRAFT.*` files assume an 830-point board and are obsolete for this
hardware. The separate large lab breadboard stays outside the dock.

## Fit evidence and uncertainty

The photo shows 17 columns of 10 holes, with no power rails. Manufacturers
publish different dimensions for this family:

| Reference | Published L × W × H |
|---|---|
| [Makerfabs](https://www.makerfabs.com/mini-bread-board-4-5x3-5cm.html) | 45 × 35 × 8.5 mm |
| [SparkFun PRT-12043](https://www.sparkfun.com/breadboard-mini-modular-white.html) | 47 × 35 × 10 mm |
| [BusBoard BB170](https://busboard.com/BB170) | 45.7 × 35.6 × 9.4 mm |
| [Arduino Uno Rev3](https://store.arduino.cc/products/arduino-uno-rev3) | PCB 68.6 × 53.4 mm |

The later ruler photos suggest approximately **47–48 × 37 × 10 mm**, including
the backing. Because the board is offset from the ruler zero, both edge
readings must be considered. Perspective and edge selection limit precision.
The current design uses a rounded-up **48 × 38 × 11 mm envelope**, then adds
mounting clearance. These numbers are approximate, not caliper measurements.
See `PHOTO_FIT_NOTES.md`.

The mini mounting outline is **56 × 44 mm**, with a **54.8 × 42.8 mm clear
interior**. That gives **6.8 mm extra length and 4.8 mm extra width** beyond the
48 × 38 mm design envelope, or **3.4 and 2.4 mm clearance per side** when centered. Center the mini board inside and secure with mounting
tape. Its 0.4 mm raised outline is a guide, not a snap fit. There are no
matching pegs, screw holes, clips, or height-dependent retainers.

The Uno rests on 5 mm raised runners with **foam mounting tape**. The whole
USB-B / barrel-jack end and the top are open. Position it so the USB plug seats
fully before sticking it down. Foam tape must keep underside components from
taking the mounting load. Optional ties must avoid headers and components.

This reduces dependence on exact dimensions. **Physical fit has not been
verified and is not guaranteed.** The 48 × 38 × 11 mm dimensions in the JSON are a conservative design
envelope derived from the ruler photos, not a claim of exact body dimensions.

## Files and regeneration

- `pod_dock.stl`: current mini-board model, **144 × 86 × 8.4 mm**.
- `pod_dock.png`: mesh top view; dashed outlines indicate component footprints.
- `pod_dock.json`: assumptions, references, dimensions and geometry checks.
- `pod_dock_fit.svg`: full-size footprints with a 100 mm scale bar.
- `make_dock.py`: source; run `uv run cad/make_dock.py` to regenerate.
- `MINI_POD_WIRING.md`: compact proposal using the firmware's existing pins.

If a paper printer is available, print the fit SVG at **100% / actual size**,
never fit-to-page, then place the physical boards on the outlines. Without a
ruler, checking the Uno against its outline still provides a useful scale
sanity check. This does not verify underside or connector clearance.

The base is 2.4 mm thick. Rear/right walls rise 6 mm above it; the front wall
rises 3 mm. Raised Y/B/G/W labels and routing slots sit in front of the mini
board. The button, LED and headers remain accessible.

To regenerate the obsolete large-board draft explicitly:
`uv run cad/make_dock.py --profile large`.

## Geometry verification

The current STL is watertight, has positive volume, and forms one connected
solid. Export/reload checks verify millimeter dimensions. All downward-facing
surfaces lie at the bed plane, so there are no elevated undersides requiring
supports. It fits the
[P1S's 256 × 256 mm build area](https://us.store.bambulab.com/products/p1s)
with room for a brim. These checks do not establish physical fit or print time.

## Slice, then submit

Open `pod_dock.stl` in **Bambu Studio → Bambu P1S, 0.4 mm nozzle**:

- Units **mm**, scale **100%**; verify **144 × 86 × 8.4 mm**.
- Broad flat base down, open side up.
- **PLA, 0.20 mm layers, 15% infill, 2 walls, supports off.**
- Black preferred, white second choice. Single color; use a paint pen on labels.
- Read the actual sliced time and review the layer preview. Issue #37 targets
  **≤ 2.5 hours**, within a 3.5-hour allowance including preparation.

**Print time is still unverified:** Bambu Studio is not installed here. No
print has been submitted. Do not scale the STL to reduce time; that changes fit.

Print-form text:

> Bambu P1S · `pod_dock.stl` · PLA · 0.20 mm layers · 15% infill · 2 walls ·
> no supports · black preferred, white second choice ·
> sliced time: **[copy from Bambu Studio]**.

After pickup, assemble with Engineer A using the mini-board wiring guide,
unplug USB while transferring the circuit, then rerun the pod sanity checks.
