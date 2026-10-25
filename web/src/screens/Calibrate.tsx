// A3 · Calibrate the board (#30): click holes 1a, 63a, 63j, 1j on the camera, then drag a handle
// until the ghost dots sit on the holes. Built on the overlay engine's calibration API (#11).

import { useRef, useState, type MutableRefObject, type PointerEvent, type ReactNode } from 'react'
import { makeCalibration, type Calibration } from '../board'
import { calibrationHoles, ROWS, type Pt } from '../board/geometry'
import { ASPECT } from '../board/media'
import { FIT, type CameraStatus, type Source } from '../app/useCamera'
import checkPaper from '../assets/figma/check-paper.svg'
import dotLive from '../assets/figma/dot-live.svg'
import { Button, Header } from '../ui/kit'
import { CameraFrame } from './Camera'
import './screens.css'

const CORNER = ['bottom-left', 'bottom-right', 'top-right', 'top-left']

type Props = {
  title: string
  chips: ReactNode
  cam: { source: Source | null; sources: Source[]; stream: MediaStream | null; status: CameraStatus; choose: (id: string) => void; retry: () => void }
  mediaRef: MutableRefObject<HTMLVideoElement | null>
  initial: Calibration | null
  onDone: (cal: Calibration) => void
  onBack: () => void
}

export function Calibrate({ title, chips, cam, mediaRef, initial, onDone, onBack }: Props) {
  const deviceId = cam.source?.id ?? 'none'
  const [clicks, setClicks] = useState<Pt[]>([])
  const [lastRow, setLastRow] = useState(initial?.lastRow ?? ROWS)
  const [size, setSize] = useState({ w: 0, h: 0 })
  const [seeded, setSeeded] = useState<string | null>(null)

  // Start from the saved calibration for this camera (recalibrate = adjust, not redo).
  if (size.w && seeded !== deviceId) {
    setSeeded(deviceId)
    setClicks(initial && initial.deviceId === deviceId ? initial.clicks.map((p) => ({ x: (p.x * size.w) / initial.videoW, y: (p.y * size.h) / initial.videoH })) : [])
  }

  const names = calibrationHoles(lastRow).map((h) => h.name)
  let cal: Calibration | null = null
  let error = ''
  if (clicks.length === 4 && size.w) {
    try {
      cal = makeCalibration(deviceId, size.w, size.h, clicks, lastRow)
    } catch (e) {
      error = (e as Error).message
    }
  }
  const n = clicks.length

  return (
    <div className="screen screen-wide calibrate">
      <Header title={title} padded>
        {chips}
      </Header>
      <div className="calibrate-body">
        <section className="cam-col">
          <div className="col-label">
            <img src={dotLive} width={10} height={10} alt="" />
            <h2 className="t-h3">Live camera</h2>
          </div>
          <CameraFrame source={cam.source} stream={cam.stream} status={cam.status} mediaRef={mediaRef} onRetry={cam.retry} onSize={setSize}>
            {({ w, h }) => <ClickLayer w={w} h={h} clicks={clicks} setClicks={setClicks} names={names} />}
          </CameraFrame>
        </section>

        <aside className="cal-panel">
          <h2 className="t-h2">Calibrate the board</h2>
          <p className="t-body-l c-60">Click the 4 corner holes once, so ALTA knows where every hole is.</p>
          <div className="cal-now">
            {n < 4 ? (
              <>
                <span className="t-label c-blue">{n + 1} of 4</span>
                <span className="t-h2">Click hole {names[n]}</span>
                <span className="t-body-l c-60">{cap(CORNER[n])} corner</span>
              </>
            ) : (
              <>
                <span className="t-label c-blue">4 of 4</span>
                <span className="t-h2">{error ? 'Try again' : 'All 4 holes set'}</span>
                <span className="t-body-l c-60">{error || 'Drag a handle to fine-tune, then press Continue.'}</span>
              </>
            )}
          </div>
          {names.map((name, i) => (
            <div key={name} className={`cal-row cal-row-${i < n ? 'done' : i === n ? 'now' : 'next'}`}>
              <span className="cal-dot">{i < n && <img src={checkPaper} width={16} height={16} alt="" />}</span>
              <span className={i === n ? 't-label' : 't-body-l'}>
                {name} · {CORNER[i]}
              </span>
            </div>
          ))}
          <label className="cal-field t-body c-60">
            Far row
            <input type="number" min={10} max={ROWS} value={lastRow} onChange={(e) => setLastRow(clampRow(+e.target.value))} title="If row 63 is out of frame, click the last row you can see and enter its number" />
          </label>
          <label className="cal-field t-body c-60">
            Camera
            <select value={cam.source?.id ?? ''} onChange={(e) => cam.choose(e.target.value)}>
              {cam.sources.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
          <span className="spacer" />
          <div className="cal-actions">
            <Button kind="secondary" onClick={() => (n ? setClicks(clicks.slice(0, -1)) : onBack())}>
              {n ? 'Undo' : 'Back'}
            </Button>
            <Button kind={cal ? 'primary' : 'locked'} chevron onClick={() => cal && onDone(cal)}>
              Continue
            </Button>
          </div>
        </aside>
      </div>
    </div>
  )
}

function ClickLayer({ w, h, clicks, setClicks, names }: { w: number; h: number; clicks: Pt[]; setClicks: (c: Pt[]) => void; names: string[] }) {
  const svgRef = useRef<SVGSVGElement>(null)
  const [drag, setDrag] = useState<number | null>(null)
  const r = Math.max(w, h) / 160

  const toVideo = (e: PointerEvent): Pt | null => {
    const ctm = svgRef.current?.getScreenCTM()
    if (!ctm) return null
    const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(ctm.inverse())
    return { x: p.x, y: p.y }
  }

  return (
    <svg
      ref={svgRef}
      className="cal-svg"
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio={ASPECT[FIT]}
      onPointerDown={(e) => {
        if (clicks.length >= 4 || drag !== null) return
        const p = toVideo(e)
        if (p) setClicks([...clicks, p])
      }}
      onPointerMove={(e) => {
        if (drag === null) return
        const p = toVideo(e)
        if (p) setClicks(clicks.map((c, i) => (i === drag ? p : c)))
      }}
      onPointerUp={() => setDrag(null)}
      onPointerLeave={() => setDrag(null)}
    >
      {clicks.length > 1 && <polygon points={clicks.map((p) => `${p.x},${p.y}`).join(' ')} fill="none" stroke="var(--blue)" strokeWidth={r / 4} strokeDasharray={`${r} ${r / 2}`} />}
      {clicks.map((p, i) => (
        <g
          key={i}
          className="cal-handle"
          onPointerDown={(e) => {
            e.stopPropagation()
            svgRef.current?.setPointerCapture(e.pointerId)
            setDrag(i)
          }}
        >
          <circle cx={p.x} cy={p.y} r={r * 1.7} fill="rgb(83 139 235 / 0.18)" stroke="var(--blue)" strokeWidth={r / 3.5} />
          <circle cx={p.x} cy={p.y} r={r / 3} fill="var(--blue)" />
          <text x={p.x + r * 2.2} y={p.y - r * 2} fill="var(--paper)" fontSize={r * 2.2} fontWeight={600} stroke="var(--ink)" strokeWidth={r / 4} paintOrder="stroke" fontFamily="Lato, sans-serif">
            {names[i]}
          </text>
        </g>
      ))}
    </svg>
  )
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)
const clampRow = (n: number) => (Number.isFinite(n) ? Math.min(ROWS, Math.max(10, Math.round(n))) : ROWS)
