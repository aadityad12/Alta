// 830-point breadboard model in millimetres, plus the hole strings from docs/CONTRACTS.md §4.
//
// Board coordinates: x runs along the board (row 1 → 63), y runs across it
// (column a → j, then the j-side rails). Row 1 / column a is the origin.
// The homography (calibration) maps these to video pixels, so which way the
// board faces in the camera doesn't matter here.
//
// Measured on the lab breadboard from the #34 sample frames (pixel spacing ÷ hole pitch):
// the center gap (e → f) and the gap from column a/j to the nearest rail row are both
// ≈ 2.9 pitches; the two rows of a rail are 1 pitch apart; each rail is 10 groups of
// 5 holes with one hole skipped between groups, level with rows 3 → 61.

export const PITCH = 2.54
export const ROWS = 63
export const COLS = 'abcdefghij'
export const GAP = 2.9 * PITCH // column e → column f, centre to centre
export const RAIL_GAP = 2.92 * PITCH // column a (or j) → the nearer rail row
export const RAIL_START = 2 * PITCH // first rail hole, measured from row 1
export const RAIL_GROUPS = 10

// Which rail row is + and which is −, nearer row first. On our board the
// a-side rails read "− +" going outwards and the j-side rails "+ −".
export const RAIL_ORDER: Record<Side, [Polarity, Polarity]> = {
  a: ['-', '+'],
  j: ['+', '-'],
}

export type Side = 'a' | 'j'
export type Polarity = '+' | '-'
export type Half = 'a-e' | 'f-j'
export type Pt = { x: number; y: number }

export type Loc =
  | { kind: 'hole'; row: number; col: string }
  | { kind: 'strip'; row: number; half: Half }
  | { kind: 'rail'; side: Side; polarity: Polarity }

/** Parse "10c", "10:a-e", "rail:a+". Throws on anything else. */
export function parseLoc(s: string): Loc {
  const str = s.trim().toLowerCase()
  let m = /^(\d{1,2})([a-j])$/.exec(str)
  if (m) return { kind: 'hole', row: checkRow(+m[1], s), col: m[2] }
  m = /^(\d{1,2}):(a-e|f-j)$/.exec(str)
  if (m) return { kind: 'strip', row: checkRow(+m[1], s), half: m[2] as Half }
  m = /^rail:([aj])([+-])$/.exec(str)
  if (m) return { kind: 'rail', side: m[1] as Side, polarity: m[2] as Polarity }
  throw new Error(`not a breadboard location: "${s}"`)
}

export function tryParseLoc(s: string): Loc | null {
  try {
    return parseLoc(s)
  } catch {
    return null
  }
}

function checkRow(row: number, s: string): number {
  if (row < 1 || row > ROWS) throw new Error(`row out of range in "${s}"`)
  return row
}

export function rowX(row: number): number {
  return (row - 1) * PITCH
}

export function colY(col: string): number {
  const i = COLS.indexOf(col)
  if (i < 0) throw new Error(`bad column "${col}"`)
  return i < 5 ? i * PITCH : 4 * PITCH + GAP + (i - 5) * PITCH
}

export function hole(row: number, col: string): Pt {
  return { x: rowX(row), y: colY(col) }
}

/** y of a rail row. */
export function railY(side: Side, polarity: Polarity): number {
  const outer = RAIL_ORDER[side].indexOf(polarity) // 0 = nearer row, 1 = outer row
  return side === 'a' ? -RAIL_GAP - outer * PITCH : colY('j') + RAIL_GAP + outer * PITCH
}

/** Every hole on one rail row, as offsets along the board. */
export function railHoleXs(): number[] {
  const xs: number[] = []
  for (let g = 0; g < RAIL_GROUPS; g++)
    for (let k = 0; k < 5; k++) xs.push(RAIL_START + (g * 6 + k) * PITCH)
  return xs
}

const RAIL_END = RAIL_START + (RAIL_GROUPS * 6 - 2) * PITCH

/** Centre of a location; for a rail, the point level with `nearRow` (or the rail's middle). */
export function center(loc: Loc, nearRow?: number): Pt {
  switch (loc.kind) {
    case 'hole':
      return hole(loc.row, loc.col)
    case 'strip':
      return { x: rowX(loc.row), y: (colY(loc.half === 'a-e' ? 'a' : 'f') + colY(loc.half === 'a-e' ? 'e' : 'j')) / 2 }
    case 'rail': {
      const x = nearRow ? clamp(rowX(nearRow), RAIL_START, RAIL_END) : (RAIL_START + RAIL_END) / 2
      return { x, y: railY(loc.side, loc.polarity) }
    }
  }
}

/** A box around the location in board mm: the hole, the 5-hole strip, or the whole rail row. */
export function bounds(loc: Loc, pad = PITCH * 0.45): { x0: number; y0: number; x1: number; y1: number } {
  switch (loc.kind) {
    case 'hole': {
      const c = hole(loc.row, loc.col)
      return { x0: c.x - pad, y0: c.y - pad, x1: c.x + pad, y1: c.y + pad }
    }
    case 'strip': {
      const [c0, c1] = loc.half === 'a-e' ? ['a', 'e'] : ['f', 'j']
      const x = rowX(loc.row)
      return { x0: x - pad, y0: colY(c0) - pad, x1: x + pad, y1: colY(c1) + pad }
    }
    case 'rail': {
      const y = railY(loc.side, loc.polarity)
      return { x0: RAIL_START - pad, y0: y - pad, x1: RAIL_END + pad, y1: y + pad }
    }
  }
}

/** The four holes the user clicks to calibrate, in click order. `lastRow` < 63 when the board's end is out of frame. */
export function calibrationHoles(lastRow = ROWS): { name: string; pt: Pt }[] {
  return [
    { name: '1a', pt: hole(1, 'a') },
    { name: `${lastRow}a`, pt: hole(lastRow, 'a') },
    { name: `${lastRow}j`, pt: hole(lastRow, 'j') },
    { name: '1j', pt: hole(1, 'j') },
  ]
}

/** Every hole on the board (main grid + 4 rails), for the ghost grid. */
export function allHoles(): Pt[] {
  const pts: Pt[] = []
  for (let r = 1; r <= ROWS; r++) for (const c of COLS) pts.push(hole(r, c))
  for (const side of ['a', 'j'] as Side[])
    for (const p of ['+', '-'] as Polarity[]) {
      const y = railY(side, p)
      for (const x of railHoleXs()) pts.push({ x, y })
    }
  return pts
}

/** The hole closest to a board point, with how far away it is (mm). Rails come back as "rail:a+". */
export function nearestHole(p: Pt): { name: string; dist: number } {
  let best = { name: '', dist: Infinity }
  for (let r = 1; r <= ROWS; r++)
    for (const c of COLS) {
      const h = hole(r, c)
      const d = Math.hypot(h.x - p.x, h.y - p.y)
      if (d < best.dist) best = { name: `${r}${c}`, dist: d }
    }
  for (const side of ['a', 'j'] as Side[])
    for (const pol of ['+', '-'] as Polarity[]) {
      const y = railY(side, pol)
      for (const x of railHoleXs()) {
        const d = Math.hypot(x - p.x, y - p.y)
        if (d < best.dist) best = { name: `rail:${side}${pol}`, dist: d }
      }
    }
  return best
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v))
}
