import { describe, expect, it } from 'vitest'
import { allHoles, bounds, center, colY, hole, nearestHole, parseLoc, PITCH, railY, rowX } from './geometry'
import { apply, invert, solveHomography } from './homography'
import { makeCalibration, rescale } from './calibration'
import { itemShapes } from './shapes'
import { labelSpots } from './annotate'
import type { LabLike } from './types'

const close = (a: number, b: number, eps = 1e-6) => expect(Math.abs(a - b)).toBeLessThan(eps)

describe('parseLoc', () => {
  it('parses the three §4 forms', () => {
    expect(parseLoc('10c')).toEqual({ kind: 'hole', row: 10, col: 'c' })
    expect(parseLoc('10:a-e')).toEqual({ kind: 'strip', row: 10, half: 'a-e' })
    expect(parseLoc('63:f-j')).toEqual({ kind: 'strip', row: 63, half: 'f-j' })
    expect(parseLoc('rail:a+')).toEqual({ kind: 'rail', side: 'a', polarity: '+' })
    expect(parseLoc(' Rail:J- ')).toEqual({ kind: 'rail', side: 'j', polarity: '-' })
  })
  it('rejects junk', () => {
    for (const s of ['0a', '64a', '10k', '10:a-f', 'rail:b+', 'row 10', '']) expect(() => parseLoc(s)).toThrow()
  })
})

describe('geometry', () => {
  it('spaces holes at 2.54 mm with a gap between e and f', () => {
    close(rowX(2) - rowX(1), PITCH)
    close(colY('b') - colY('a'), PITCH)
    expect(colY('f') - colY('e')).toBeGreaterThan(2.5 * PITCH)
    close(colY('j') - colY('f'), 4 * PITCH)
  })
  it('puts the a-side rails below column a and the j-side rails above column j', () => {
    expect(railY('a', '+')).toBeLessThan(0)
    expect(railY('a', '-')).toBeLessThan(0)
    expect(railY('j', '+')).toBeGreaterThan(colY('j'))
    close(Math.abs(railY('a', '+') - railY('a', '-')), PITCH)
  })
  it('centres a strip between its end holes', () => {
    const c = center(parseLoc('10:a-e'))
    close(c.x, rowX(10))
    close(c.y, 2 * PITCH)
    const b = bounds(parseLoc('10:f-j'), 0)
    close(b.y0, colY('f'))
    close(b.y1, colY('j'))
  })
  it('counts 630 grid holes + 4 rails of 50', () => {
    expect(allHoles()).toHaveLength(630 + 200)
  })
  it('finds the nearest hole', () => {
    expect(nearestHole({ x: rowX(10) + 0.4, y: colY('c') - 0.3 })).toMatchObject({ name: '10c' })
    expect(nearestHole({ x: rowX(10), y: railY('a', '+') + 0.2 })).toMatchObject({ name: 'rail:a+' })
  })
})

describe('homography', () => {
  it('maps a unit square onto a scaled, shifted square (affine case)', () => {
    const src = [{ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 1, y: 1 }, { x: 0, y: 1 }]
    const dst = src.map((p) => ({ x: 100 + 50 * p.x, y: 20 + 50 * p.y }))
    const H = solveHomography(src, dst)
    const p = apply(H, 0.5, 0.25)
    close(p.x, 125)
    close(p.y, 32.5)
  })
  it('maps the 4 corners of a skewed quad exactly and round-trips through the inverse', () => {
    const src = [hole(1, 'a'), hole(63, 'a'), hole(63, 'j'), hole(1, 'j')]
    const dst = [{ x: 399.6, y: 355.1 }, { x: 1378.9, y: 342.4 }, { x: 1380.9, y: 165.4 }, { x: 393.1, y: 181.6 }]
    const H = solveHomography(src, dst)
    src.forEach((s, i) => {
      const p = apply(H, s.x, s.y)
      close(p.x, dst[i].x, 1e-6)
      close(p.y, dst[i].y, 1e-6)
    })
    const Hi = invert(H)
    const q = apply(H, rowX(30), colY('g'))
    const back = apply(Hi, q.x, q.y)
    close(back.x, rowX(30), 1e-6)
    close(back.y, colY('g'), 1e-6)
  })
  it('handles real perspective (a trapezoid)', () => {
    const src = [{ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 10, y: 10 }, { x: 0, y: 10 }]
    const dst = [{ x: 0, y: 0 }, { x: 100, y: 0 }, { x: 80, y: 60 }, { x: 20, y: 60 }]
    const H = solveHomography(src, dst)
    const mid = apply(H, 5, 5)
    close(mid.x, 50)
    expect(mid.y).toBeGreaterThan(30) // the far half is foreshortened
  })
  it('refuses collinear points', () => {
    const src = [{ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 2, y: 0 }, { x: 0, y: 1 }]
    expect(() => solveHomography(src, src)).toThrow()
  })
})

// The sample frame docs/samples/board-empty-01.jpg, calibrated on its 4 corner holes.
const SAMPLE = [{ x: 399.6, y: 355.1 }, { x: 1378.9, y: 342.4 }, { x: 1380.9, y: 165.4 }, { x: 393.1, y: 181.6 }]

describe('calibration', () => {
  it('rescales to another video size', () => {
    const cal = makeCalibration('cam', 1600, 900, SAMPLE)
    const half = rescale(cal, 800, 450)
    const a = apply(cal.H, rowX(10), colY('c'))
    const b = apply(half.H, rowX(10), colY('c'))
    close(b.x, a.x / 2, 1e-6)
    close(b.y, a.y / 2, 1e-6)
  })
  it('supports a far row other than 63', () => {
    const cal = makeCalibration('cam', 1600, 900, SAMPLE, 63)
    const far = apply(cal.H, rowX(50), colY('a'))
    const cal50 = makeCalibration('cam', 1600, 900, [SAMPLE[0], far, apply(cal.H, rowX(50), colY('j')), SAMPLE[3]], 50)
    const p = apply(cal50.H, rowX(63), colY('j'))
    close(p.x, SAMPLE[2].x, 1e-3)
    close(p.y, SAMPLE[2].y, 1e-3)
  })
})

describe('itemShapes', () => {
  const H = makeCalibration('cam', 1600, 900, SAMPLE).H
  const lab: LabLike = { parts: [{ ref: 'D1', kind: 'led', pins: { anode: '10d', cathode: '13d' } }, { ref: 'W1', kind: 'wire', pins: { 1: 'rail:a+', 2: '6a' } }] }

  it('draws every kind', () => {
    const { shapes, warnings } = itemShapes(
      [
        { id: 'h', kind: 'hole', at: '10c', style: 'probe-Y', pulse: true },
        { id: 's', kind: 'strip', at: '10:a-e' },
        { id: 'r', kind: 'rail', at: 'rail:a+', style: 'bad' },
        { id: 'a', kind: 'arrow', from: '6c', to: '10c' },
        { id: 'l', kind: 'label', at: '10c', text: 'Yellow here' },
        { id: 'c', kind: 'component', ref: 'd1' },
        { id: 'w', kind: 'component', ref: 'W1' },
      ],
      H,
      lab,
    )
    expect(warnings).toEqual([])
    const keys = shapes.map((s) => s.key)
    expect(keys).toEqual(expect.arrayContaining(['h', 's', 'r', 'a-shaft', 'a-head', 'l', 'c-body0', 'c-pin0', 'c-pin1', 'w-pin0']))
    const h = shapes.find((s) => s.key === 'h')!
    expect(h).toMatchObject({ t: 'poly', style: 'probe-Y', pulse: true, fill: false })
  })
  it('lands a strip highlight on its row in the sample photo', () => {
    // Row 10, a–e in board-empty-01.jpg is at x ≈ 539 px, y ≈ 285–350 px (hole centres from the photo).
    const s = itemShapes([{ id: 's', kind: 'strip', at: '10:a-e' }], H).shapes[0]
    if (s.t !== 'poly') throw new Error('expected a polygon')
    const cx = s.pts.reduce((t, p) => t + p.x, 0) / s.pts.length
    expect(Math.abs(cx - 539)).toBeLessThan(4)
  })
  it('skips bad items with a warning instead of throwing', () => {
    const { shapes, warnings } = itemShapes(
      [
        { id: 'x', kind: 'strip', at: 'row ten' },
        { id: 'y', kind: 'component', ref: 'Q9' },
        { id: 'z', kind: 'label', at: '10c' },
        { id: 'ok', kind: 'hole', at: '1a' },
      ],
      H,
      lab,
    )
    expect(shapes.map((s) => s.key)).toEqual(['ok'])
    expect(warnings).toHaveLength(3)
  })
})

describe('annotated frame labels', () => {
  it('numbers rows 1, 5, 10 … 60 on both sides and letters every column at both ends', () => {
    const texts = labelSpots().map((s) => s.text)
    expect(texts.filter((t) => t === '10')).toHaveLength(2)
    expect(texts.filter((t) => t === 'j')).toHaveLength(2)
    expect(texts).toContain('60')
    expect(texts).not.toContain('62')
  })
})
