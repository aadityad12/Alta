// 3×3 homography from 4 point pairs (DLT with h33 = 1: an 8×8 linear system).

import type { Pt } from './geometry'

/** Row-major [h11 h12 h13 h21 h22 h23 h31 h32 h33]. */
export type H = number[]

/** H that maps each src[i] onto dst[i]. Throws if three of the points are (nearly) collinear. */
export function solveHomography(src: Pt[], dst: Pt[]): H {
  if (src.length !== 4 || dst.length !== 4) throw new Error('need exactly 4 point pairs')
  const A: number[][] = []
  for (let i = 0; i < 4; i++) {
    const { x, y } = src[i]
    const { x: u, y: v } = dst[i]
    A.push([x, y, 1, 0, 0, 0, -u * x, -u * y, u])
    A.push([0, 0, 0, x, y, 1, -v * x, -v * y, v])
  }
  const h = gaussSolve(A)
  return [...h, 1]
}

/** Solve the augmented n×(n+1) system in place with partial pivoting. */
function gaussSolve(A: number[][]): number[] {
  const n = A.length
  const scale = Math.max(...A.flat().map(Math.abs)) || 1
  for (let c = 0; c < n; c++) {
    let p = c
    for (let r = c + 1; r < n; r++) if (Math.abs(A[r][c]) > Math.abs(A[p][c])) p = r
    if (Math.abs(A[p][c]) < 1e-12 * scale) throw new Error('degenerate points: pick 4 corners, no 3 in a line')
    ;[A[c], A[p]] = [A[p], A[c]]
    for (let r = 0; r < n; r++) {
      if (r === c) continue
      const f = A[r][c] / A[c][c]
      if (f !== 0) for (let k = c; k <= n; k++) A[r][k] -= f * A[c][k]
    }
  }
  return A.map((row, i) => row[n] / row[i])
}

export function apply(H: H, x: number, y: number): Pt {
  const w = H[6] * x + H[7] * y + H[8]
  return { x: (H[0] * x + H[1] * y + H[2]) / w, y: (H[3] * x + H[4] * y + H[5]) / w }
}

export function applyPt(H: H, p: Pt): Pt {
  return apply(H, p.x, p.y)
}

export function invert(H: H): H {
  const [a, b, c, d, e, f, g, h, i] = H
  const A = e * i - f * h
  const B = -(d * i - f * g)
  const C = d * h - e * g
  const det = a * A + b * B + c * C
  if (Math.abs(det) < 1e-15) throw new Error('homography is not invertible')
  const inv = [A, -(b * i - c * h), b * f - c * e, B, a * i - c * g, -(a * f - c * d), C, -(a * h - b * g), a * e - b * d]
  return inv.map((v) => v / det)
}

/** Local scale of H around p (pixels per board unit), for sizing strokes and labels. */
export function scaleAt(H: H, p: Pt, d = 1): number {
  const a = apply(H, p.x, p.y)
  const b = apply(H, p.x + d, p.y)
  const c = apply(H, p.x, p.y + d)
  return (Math.hypot(b.x - a.x, b.y - a.y) + Math.hypot(c.x - a.x, c.y - a.y)) / (2 * d)
}
