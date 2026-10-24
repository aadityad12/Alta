// <BoardOverlay>: an SVG layer exactly on top of the camera <video> (or a sample <img>).
//
// The SVG's viewBox is the video's own pixel grid and its preserveAspectRatio copies the
// media's object-fit, so the browser maps video pixels → screen for us: letterboxing,
// cropping and window resizes all stay aligned without any JS.

import { useEffect, useMemo } from 'react'
import { ASPECT, type Fit } from './media'
import { allHoles, type Pt } from './geometry'
import { applyPt, scaleAt, type H } from './homography'
import { rescale, type Calibration } from './calibration'
import { itemShapes, type Shape } from './shapes'
import { STYLE_COLOR, STYLE_INK } from './styles'
import type { LabLike, OverlayItem } from './types'
import './overlay.css'

type Props = {
  items: OverlayItem[]
  calibration: Calibration | null
  lab?: LabLike | null
  videoW: number // intrinsic size: video.videoWidth / img.naturalWidth
  videoH: number
  fit?: Fit // must match the media element's object-fit (default contain)
  ghost?: boolean // faint dot on every hole: shows a bad calibration at a glance
}

export function BoardOverlay({ items, calibration, lab, videoW, videoH, fit = 'contain', ghost = false }: Props) {
  const cal = calibration && videoW > 0 && videoH > 0 ? rescale(calibration, videoW, videoH) : null
  const { shapes, warnings } = useMemo(
    () => (cal ? itemShapes(items, cal.H, lab) : { shapes: [], warnings: [] }),
    [items, cal, lab],
  )
  useEffect(() => {
    if (warnings.length) console.warn('[overlay] skipped:', warnings.join('; '))
  }, [warnings])

  if (!cal) return null
  return (
    <svg className="bo-svg" viewBox={`0 0 ${videoW} ${videoH}`} preserveAspectRatio={ASPECT[fit]}>
      {ghost && <GhostGrid H={cal.H} />}
      {shapes.map((s) => (
        <ShapeView key={s.key} s={s} />
      ))}
    </svg>
  )
}

function ShapeView({ s }: { s: Shape }) {
  const color = STYLE_COLOR[s.style]
  const cls = `bo-shape${s.t !== 'pill' && s.pulse ? ' bo-pulse' : ''}`
  switch (s.t) {
    case 'poly':
      return (
        <polygon
          className={cls}
          points={s.pts.map((p) => `${p.x},${p.y}`).join(' ')}
          fill={s.fill ? color : 'none'}
          fillOpacity={s.fill ? (s.width ? 0.22 : 1) : undefined}
          stroke={s.width ? color : 'none'}
          strokeWidth={s.width}
          strokeLinejoin="round"
        />
      )
    case 'line':
      return (
        <line className={cls} x1={s.a.x} y1={s.a.y} x2={s.b.x} y2={s.b.y} stroke={color} strokeOpacity={0.85} strokeWidth={s.width} strokeLinecap="round" />
      )
    case 'pill': {
      const w = s.text.length * s.size * 0.58 + s.size
      const h = s.size * 1.6
      const y = s.at.y - h * 1.4 // float above the spot it names
      return (
        <g className={cls} fontSize={s.size}>
          <line x1={s.at.x} y1={s.at.y} x2={s.at.x} y2={y + h / 2} stroke={color} strokeWidth={Math.max(2, s.size / 8)} />
          <rect x={s.at.x - w / 2} y={y - h / 2} width={w} height={h} rx={h / 2} fill={color} />
          <text className="bo-pill" x={s.at.x} y={y} fill={STYLE_INK[s.style]} textAnchor="middle" dominantBaseline="central">
            {s.text}
          </text>
        </g>
      )
    }
  }
}

/** Faint dot on every hole the calibration predicts. */
export function GhostGrid({ H }: { H: H }) {
  const d = useMemo(() => {
    const holes = allHoles()
    const r = Math.max(1.2, 0.32 * scaleAt(H, holes[0]))
    return holes
      .map((h: Pt) => {
        const p = applyPt(H, h)
        return `M${p.x - r},${p.y}a${r},${r} 0 1,0 ${2 * r},0a${r},${r} 0 1,0 ${-2 * r},0`
      })
      .join('')
  }, [H])
  return <path className="bo-ghost" d={d} strokeWidth={0.6} />
}
