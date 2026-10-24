# Overlay engine (`web/src/board/`, #11)

Turns breadboard coordinates (`"10c"`, `"10:a-e"`, `"rail:a+"`, from docs/CONTRACTS.md §4) into pixels on the live camera video. Claude never deals in pixels: it names holes, and this module draws them.

**Try it:** `npm run dev`, then open <http://localhost:5173/dev/board>. It works on the #34 sample photos and video, with no camera or server needed. *Cameras…* switches to a real webcam, and *live* connects to the server's `/ws` and acts as the student screen for overlays and `look_at_board`.

## Using it in the app (#30)

```tsx
import { BoardOverlay, CalibrationLayer, captureAnnotatedFrame, loadCalibration, saveCalibration, useMediaSize } from './board'

const videoRef = useRef<HTMLVideoElement>(null)
const { w, h } = useMediaSize(videoRef)                    // the video's intrinsic size
const [cal, setCal] = useState(() => loadCalibration(deviceId))

<div style={{ position: 'relative' }}>                       {/* the overlay fills this box */}
  <video ref={videoRef} style={{ width: '100%', height: '100%', objectFit: 'contain' }} … />
  <BoardOverlay items={items} calibration={cal} lab={lab} videoW={w} videoH={h} fit="contain" />
  {calibrating && (
    <CalibrationLayer deviceId={deviceId} videoW={w} videoH={h} fit="contain" initial={cal}
      onDone={(c) => { saveCalibration(c); setCal(c); setCalibrating(false) }}
      onCancel={() => setCalibrating(false)} />
  )}
</div>
```

- **`items`**: the `OverlayItem[]` from the `overlay` message (`mode: "add"` appends, `"replace"` replaces; `overlay_clear` empties the list). For an `expect` message, add a strip item yourself: `{id: 'expect-Y', kind: 'strip', at, style: 'probe-Y', pulse: true}`.
- **`lab`**: the `lab` message payload. It's only needed for `kind: "component"`, which highlights a part's pins from `lab.parts`.
- **`fit`** must match the video's CSS `object-fit` (`contain` or `cover`, centred). The overlay is an SVG whose viewBox is the video's own pixel grid, so it stays aligned through resizes and letterboxing without any JS.
- Bad items (unknown hole, missing `ref`, …) are skipped with a `console.warn`. They never throw.
- **Calibration:** the user clicks holes `1a`, `63a`, `63j`, `1j`, then drags any handle until the cyan ghost dots sit on the holes. If row 63 is out of frame, they click the last visible row and type its number in *far row*. It's saved in `localStorage` per `deviceId`, so a page reload keeps it. Pass `initial={cal}` and recalibrating starts from the old clicks.
- **`look_at_board`**: on `request_frame`, reply with `{type: 'frame', id, ...captureAnnotatedFrame(videoRef.current, cal)}`. That's the frame at 1280 px wide, with row numbers every 5 rows, column letters and rail +/− drawn on it, as a JPEG at quality 0.8 (≈140 KB). Without a calibration it sends the plain frame.

Colours live in `styles.ts` (placeholders until the #26 spec) and animation in `overlay.css` (`.bo-pulse`).

## Files

| file | what |
|---|---|
| `geometry.ts` | board model in mm, `parseLoc`, hole/strip/rail positions, `nearestHole` |
| `homography.ts` | 4-point homography (8×8 solve), `apply`, `invert` |
| `calibration.ts` | `Calibration` type, make/rescale, `localStorage` save/load |
| `shapes.ts` | OverlayItems → polygons/lines/pills in video pixels (pure) |
| `BoardOverlay.tsx`, `CalibrationLayer.tsx`, `media.ts` | the React layers, `useMediaSize`, object-fit mapping |
| `annotate.ts` | `captureAnnotatedFrame` |
| `board.test.ts` | `npm test` |

## Board model

Measured on our lab breadboard from `docs/samples/board-empty-01.jpg`: hole pitch 2.54 mm, center gap e→f = 2.9 pitches, column a/j → nearer rail row = 2.92 pitches, rail rows 1 pitch apart, and each rail is 10 groups of 5 holes level with rows 3 → 61. Calibrated on just the 4 corner holes, the model puts all 630 grid holes within 0.4 mm of where they are in the photo (0.22 mm on average) and the 200 rail holes within 0.8 mm.

Rail polarity on our board: on the a side the rail nearer the holes is **−** and the outer one is **+**; on the j side, + is nearer and − is outer. If a different board is used, change `RAIL_ORDER` in `geometry.ts`.
