// captureAnnotatedFrame: the photo Claude sees when it calls look_at_board (#20).
// The current frame, ~1280 px wide, with faint row numbers every 5 rows and column
// letters drawn at the board's edges, so Claude can name holes the way the student sees them.

import { COLS, hole, PITCH, railY, ROWS, rowX, type Polarity, type Pt, type Side } from './geometry'
import { applyPt, scaleAt, type H } from './homography'
import { rescale, type Calibration } from './calibration'

export type AnnotatedFrame = { jpeg_b64: string; w: number; h: number }

type Source = HTMLVideoElement | HTMLImageElement | HTMLCanvasElement

export function captureAnnotatedFrame(source: Source, calibration: Calibration | null, opts: { width?: number; quality?: number } = {}): AnnotatedFrame {
  const { width = 1280, quality = 0.8 } = opts
  const [vw, vh] = sourceSize(source)
  if (!vw || !vh) throw new Error('no frame yet (video not playing?)')
  const k = Math.min(1, width / vw)
  const w = Math.round(vw * k)
  const h = Math.round(vh * k)

  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('no 2D canvas')
  ctx.drawImage(source, 0, 0, w, h)
  if (calibration) drawLabels(ctx, scaleH(rescale(calibration, vw, vh).H, k))

  const url = canvas.toDataURL('image/jpeg', quality)
  return { jpeg_b64: url.slice(url.indexOf(',') + 1), w, h }
}

function sourceSize(s: Source): [number, number] {
  if (s instanceof HTMLVideoElement) return [s.videoWidth, s.videoHeight]
  if (s instanceof HTMLImageElement) return [s.naturalWidth, s.naturalHeight]
  return [s.width, s.height]
}

/** H followed by a uniform scale k (video px → canvas px). */
function scaleH(H: H, k: number): H {
  return [H[0] * k, H[1] * k, H[2] * k, H[3] * k, H[4] * k, H[5] * k, H[6], H[7], H[8]]
}

/** Where the labels go, in board mm. Exported for tests. */
export function labelSpots(): { text: string; at: Pt }[] {
  const spots: { text: string; at: Pt }[] = []
  const outerA = Math.min(railY('a', '+'), railY('a', '-'))
  const outerJ = Math.max(railY('j', '+'), railY('j', '-'))
  const rows = [1]
  for (let r = 5; r <= ROWS; r += 5) rows.push(r)
  for (const r of rows) {
    spots.push({ text: String(r), at: { x: rowX(r), y: outerA - 1.6 * PITCH } })
    spots.push({ text: String(r), at: { x: rowX(r), y: outerJ + 1.6 * PITCH } })
  }
  for (const c of COLS) {
    spots.push({ text: c, at: { x: rowX(1) - 1.8 * PITCH, y: hole(1, c).y } })
    spots.push({ text: c, at: { x: rowX(ROWS) + 1.8 * PITCH, y: hole(1, c).y } })
  }
  for (const side of ['a', 'j'] as Side[])
    for (const p of ['+', '-'] as Polarity[]) {
      const text = p === '+' ? '+' : '−'
      spots.push({ text, at: { x: rowX(1) - 1.8 * PITCH, y: railY(side, p) } })
      spots.push({ text, at: { x: rowX(ROWS) + 1.8 * PITCH, y: railY(side, p) } })
    }
  return spots
}

function drawLabels(ctx: CanvasRenderingContext2D, H: H): void {
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.lineJoin = 'round'
  for (const { text, at } of labelSpots()) {
    const p = applyPt(H, at)
    const size = Math.min(26, Math.max(11, 1.1 * PITCH * scaleAt(H, at)))
    ctx.font = `700 ${size}px system-ui, sans-serif`
    ctx.lineWidth = Math.max(2, size / 4)
    ctx.strokeStyle = 'rgba(0, 0, 0, 0.7)'
    ctx.fillStyle = 'rgba(255, 255, 255, 0.92)'
    ctx.strokeText(text, p.x, p.y)
    ctx.fillText(text, p.x, p.y)
  }
}
