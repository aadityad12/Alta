// Calibration UI: click 4 holes (1a, 63a, 63j, 1j) on the video, then drag any handle to
// fine-tune while the ghost grid shows every hole the calibration predicts.

import { useRef, useState, type PointerEvent } from 'react'
import { calibrationHoles, ROWS, type Pt } from './geometry'
import { makeCalibration, type Calibration } from './calibration'
import { GhostGrid } from './BoardOverlay'
import { ASPECT, type Fit } from './media'
import './overlay.css'

type Props = {
  deviceId: string
  videoW: number
  videoH: number
  fit?: Fit
  initial?: Calibration | null // start from the old clicks (recalibrate = adjust, not redo)
  onDone: (cal: Calibration) => void
  onCancel: () => void
}

const HINT = ['row 1, column a', 'the far row, column a', 'the far row, column j', 'row 1, column j']

export function CalibrationLayer({ deviceId, videoW, videoH, fit = 'contain', initial, onDone, onCancel }: Props) {
  const svgRef = useRef<SVGSVGElement>(null)
  const [clicks, setClicks] = useState<Pt[]>(initial ? rescaleClicks(initial, videoW, videoH) : [])
  const [lastRow, setLastRow] = useState(initial?.lastRow ?? ROWS)
  const [drag, setDrag] = useState<number | null>(null)

  let cal: Calibration | null = null
  let error = ''
  if (clicks.length === 4) {
    try {
      cal = makeCalibration(deviceId, videoW, videoH, clicks, lastRow)
    } catch (e) {
      error = (e as Error).message
    }
  }

  const toVideo = (e: PointerEvent): Pt | null => {
    const svg = svgRef.current
    const ctm = svg?.getScreenCTM()
    if (!svg || !ctm) return null
    const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(ctm.inverse())
    return { x: p.x, y: p.y }
  }

  const onDown = (e: PointerEvent<SVGSVGElement>) => {
    if (clicks.length >= 4 || drag !== null) return
    const p = toVideo(e)
    if (p) setClicks([...clicks, p])
  }
  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    if (drag === null) return
    const p = toVideo(e)
    if (p) setClicks(clicks.map((c, i) => (i === drag ? p : c)))
  }

  const names = calibrationHoles(lastRow).map((h) => h.name)
  const r = Math.max(videoW, videoH) / 160
  const prompt =
    clicks.length < 4
      ? `Click hole ${names[clicks.length]} (${HINT[clicks.length]})`
      : error || 'Drag a handle until the dots sit on the holes'

  return (
    <>
      <svg
        ref={svgRef}
        className="bo-svg bo-cal"
        viewBox={`0 0 ${videoW} ${videoH}`}
        preserveAspectRatio={ASPECT[fit]}
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={() => setDrag(null)}
        onPointerLeave={() => setDrag(null)}
      >
        {cal && <GhostGrid H={cal.H} />}
        {clicks.length > 1 && (
          <polygon points={clicks.map((p) => `${p.x},${p.y}`).join(' ')} fill="none" stroke="#38bdf8" strokeWidth={r / 4} strokeDasharray={`${r} ${r / 2}`} />
        )}
        {clicks.map((p, i) => (
          <g
            key={i}
            className="bo-handle"
            onPointerDown={(e) => {
              e.stopPropagation()
              ;(e.currentTarget.ownerSVGElement as SVGSVGElement).setPointerCapture(e.pointerId)
              setDrag(i)
            }}
          >
            <circle cx={p.x} cy={p.y} r={r * 1.6} fill="rgb(56 189 248 / 0.15)" stroke="#38bdf8" strokeWidth={r / 4} />
            <line x1={p.x - r * 2.4} y1={p.y} x2={p.x + r * 2.4} y2={p.y} stroke="#38bdf8" strokeWidth={r / 6} />
            <line x1={p.x} y1={p.y - r * 2.4} x2={p.x} y2={p.y + r * 2.4} stroke="#38bdf8" strokeWidth={r / 6} />
            <text x={p.x + r * 2} y={p.y - r * 2} fill="#38bdf8" fontSize={r * 2.2} fontWeight={700} stroke="#0f172a" strokeWidth={r / 5} paintOrder="stroke">
              {names[i]}
            </text>
          </g>
        ))}
      </svg>
      <div className="bo-cal-bar">
        <span>{prompt}</span>
        <label title="If row 63 is out of frame, click the last row you can see and enter its number">
          far row <input type="number" min={10} max={ROWS} value={lastRow} onChange={(e) => setLastRow(clampRow(+e.target.value))} />
        </label>
        <button onClick={() => setClicks(clicks.slice(0, -1))} disabled={!clicks.length}>
          Undo
        </button>
        <button onClick={() => cal && onDone(cal)} disabled={!cal}>
          Done
        </button>
        <button onClick={onCancel}>Cancel</button>
      </div>
    </>
  )
}

function clampRow(n: number): number {
  return Number.isFinite(n) ? Math.min(ROWS, Math.max(10, Math.round(n))) : ROWS
}

function rescaleClicks(cal: Calibration, w: number, h: number): Pt[] {
  return cal.clicks.map((p) => ({ x: (p.x * w) / cal.videoW, y: (p.y * h) / cal.videoH }))
}
