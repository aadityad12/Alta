// OverlayItems → flat shapes in video pixels. Pure, so it's unit-tested without a browser.

import { bounds, center, hole, parseLoc, PITCH, type Loc, type Pt } from './geometry'
import { applyPt, scaleAt, type H } from './homography'
import type { LabLike, OverlayItem, OverlayStyle } from './types'

export type Shape =
  | { t: 'poly'; key: string; pts: Pt[]; style: OverlayStyle; pulse: boolean; width: number; fill: boolean }
  | { t: 'line'; key: string; a: Pt; b: Pt; style: OverlayStyle; pulse: boolean; width: number }
  | { t: 'pill'; key: string; at: Pt; text: string; style: OverlayStyle; size: number }

export type ShapeResult = { shapes: Shape[]; warnings: string[] }

const RING_R = 0.62 * PITCH // hole ring radius, mm
const BOX_PAD = 0.62 * PITCH // strip / rail outline padding, mm

export function itemShapes(items: OverlayItem[], H: H, lab?: LabLike | null): ShapeResult {
  const out: ShapeResult = { shapes: [], warnings: [] }
  for (const item of items) {
    try {
      addItem(out.shapes, item, H, lab)
    } catch (e) {
      out.warnings.push(`${item.id}: ${(e as Error).message}`)
    }
  }
  return out
}

function addItem(shapes: Shape[], item: OverlayItem, H: H, lab?: LabLike | null): void {
  const style = item.style ?? 'attention'
  const pulse = !!item.pulse
  const key = item.id
  const need = (s: string | undefined, field: string): string => {
    if (!s) throw new Error(`${item.kind} needs "${field}"`)
    return s
  }

  switch (item.kind) {
    case 'hole': {
      const loc = parseLoc(need(item.at, 'at'))
      if (loc.kind !== 'hole') {
        boxShape(shapes, key, loc, H, style, pulse) // be forgiving: a strip/rail given as a "hole"
        return
      }
      ringShape(shapes, key, hole(loc.row, loc.col), H, style, pulse)
      return
    }
    case 'strip':
    case 'rail':
      boxShape(shapes, key, parseLoc(need(item.at, 'at')), H, style, pulse)
      return
    case 'label': {
      const loc = parseLoc(need(item.at, 'at'))
      shapes.push(pillShape(key, loc, H, need(item.text, 'text'), style))
      return
    }
    case 'arrow': {
      const from = parseLoc(need(item.from, 'from'))
      const to = parseLoc(need(item.to, 'to'))
      arrowShapes(shapes, key, center(from, rowOf(to)), center(to, rowOf(from)), H, style, pulse)
      return
    }
    case 'component': {
      const ref = need(item.ref, 'ref')
      const part = lab?.parts?.find((p) => p.ref.toLowerCase() === ref.toLowerCase())
      if (!part) throw new Error(`no part "${ref}" in the lab`)
      const locs = Object.values(part.pins).map((s) => parseLoc(s))
      const boardRow = locs.map(rowOf).find((r) => r !== undefined)
      const pts = locs.map((l) => (l.kind === 'hole' ? hole(l.row, l.col) : center(l, boardRow)))
      for (let i = 0; i + 1 < pts.length; i++) {
        const a = applyPt(H, pts[i])
        const b = applyPt(H, pts[i + 1])
        shapes.push({ t: 'line', key: `${key}-body${i}`, a, b, style, pulse, width: 1.1 * PITCH * scaleAt(H, pts[i]) })
      }
      pts.forEach((p, i) => ringShape(shapes, `${key}-pin${i}`, p, H, style, pulse))
      return
    }
    default:
      throw new Error(`unknown kind "${(item as OverlayItem).kind}"`)
  }
}

function rowOf(loc: Loc): number | undefined {
  return loc.kind === 'rail' ? undefined : loc.row
}

function ringShape(shapes: Shape[], key: string, c: Pt, H: H, style: OverlayStyle, pulse: boolean): void {
  const pts: Pt[] = []
  for (let i = 0; i < 24; i++) {
    const a = (i / 24) * 2 * Math.PI
    pts.push(applyPt(H, { x: c.x + RING_R * Math.cos(a), y: c.y + RING_R * Math.sin(a) }))
  }
  shapes.push({ t: 'poly', key, pts, style, pulse, width: strokeAt(H, c), fill: false })
}

function boxShape(shapes: Shape[], key: string, loc: Loc, H: H, style: OverlayStyle, pulse: boolean): void {
  const b = bounds(loc, BOX_PAD)
  const corners = [
    { x: b.x0, y: b.y0 },
    { x: b.x1, y: b.y0 },
    { x: b.x1, y: b.y1 },
    { x: b.x0, y: b.y1 },
  ]
  // Long rail outlines curve slightly under perspective, so subdivide the long edges.
  const pts: Pt[] = []
  for (let i = 0; i < 4; i++) {
    const p = corners[i]
    const q = corners[(i + 1) % 4]
    const n = Math.max(1, Math.round(Math.hypot(q.x - p.x, q.y - p.y) / (4 * PITCH)))
    for (let k = 0; k < n; k++) pts.push(applyPt(H, { x: p.x + ((q.x - p.x) * k) / n, y: p.y + ((q.y - p.y) * k) / n }))
  }
  shapes.push({ t: 'poly', key, pts, style, pulse, width: strokeAt(H, center(loc)), fill: true })
}

function pillShape(key: string, loc: Loc, H: H, text: string, style: OverlayStyle): Shape {
  const c = center(loc)
  const s = scaleAt(H, c)
  const at = applyPt(H, c)
  return { t: 'pill', key, at, text, style, size: clamp(1.5 * PITCH * s, 12, 28) }
}

function arrowShapes(shapes: Shape[], key: string, from: Pt, to: Pt, H: H, style: OverlayStyle, pulse: boolean): void {
  const a = applyPt(H, from)
  const b = applyPt(H, to)
  const len = Math.hypot(b.x - a.x, b.y - a.y)
  if (len < 1) return
  const s = scaleAt(H, to)
  const trim = Math.min(RING_R * s, len / 3) // stop at the target's ring, not on the hole
  const ux = (b.x - a.x) / len
  const uy = (b.y - a.y) / len
  const tip = { x: b.x - ux * trim, y: b.y - uy * trim }
  const width = strokeAt(H, to)
  const head = Math.max(width * 3.5, PITCH * s)
  const base = { x: tip.x - ux * head, y: tip.y - uy * head }
  shapes.push({ t: 'line', key: `${key}-shaft`, a, b: base, style, pulse, width })
  shapes.push({
    t: 'poly',
    key: `${key}-head`,
    pts: [tip, { x: base.x - uy * head * 0.55, y: base.y + ux * head * 0.55 }, { x: base.x + uy * head * 0.55, y: base.y - ux * head * 0.55 }],
    style,
    pulse,
    width: 0,
    fill: true,
  })
}

function strokeAt(H: H, p: Pt): number {
  return Math.max(2, 0.28 * PITCH * scaleAt(H, p))
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v))
}
