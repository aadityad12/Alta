// Intro (Figma "Intro 1 → 3"): the A's blue wire hangs loose (Frame 4 pose), is dragged over and
// plugged in, then the mark zooms out into the Alta wordmark. ~1.75 s; click or any key skips it.
// Geometry is the Figma mark's own (Intro 2 size: 286.7 × 439.6), so the frames line up exactly.

import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import './screens.css'

type P = [number, number]
type Curve = [P, P, P, P]

const DANGLE: Curve = [[28.6, 257.9], [158.29, 343.71], [66.14, 496.6], [206.11, 456.34]]
const LIFT: Curve = [[28.6, 257.9], [80, 345], [250, 300], [322, 160]]
const PLUGGED: Curve = [[28.6, 257.9], [28.6, 257.9], [143.29, 257.9], [257.97, 181.49]]
const ORANGE = 'M257.97 257.91 C257.97 257.91 143.29 305.68 28.6 181.5'

const S = 57.3 // square size
const C = [0, 76.45, 152.9, 229.4] // columns
const R = [0, 76.5, 152.9, 229.4, 305.8, 382.3] // rows
const SQUARES: P[] = [[C[1], R[0]], [C[2], R[0]], ...R.slice(1).flatMap((y): P[] => [[C[0], y], [C[3], y]])]

// where the mark sits on the 1440 × 900 stage: big (Intro 2) → small (Intro 3)
const BIG = { x: 576.6, y: 230.2, s: 1 }
const SMALL = { x: 455, y: 331, s: 126.81 / 286.7 }

// timeline (ms)
const T_DRAG = 200, T_SNAP = 500, T_HOLD = 650, T_ZOOM = 730, T_ZOOM_END = 1180, T_FADE = 1480, T_END = 1730

const clamp = (t: number) => Math.min(1, Math.max(0, t))
const inOut = (t: number) => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2)
const outBack = (t: number) => 1 + 2.2 * (t - 1) ** 3 + 1.2 * (t - 1) ** 2
const mix = (a: Curve, b: Curve, t: number): Curve => a.map((p, i) => [p[0] + (b[i][0] - p[0]) * t, p[1] + (b[i][1] - p[1]) * t]) as Curve
const d = (c: Curve) => `M${c[0]} C${c[1]} ${c[2]} ${c[3]}`

export function Intro({ onDone }: { onDone: () => void }) {
  const root = useRef<HTMLDivElement>(null)
  const mark = useRef<SVGSVGElement>(null)
  const blue = useRef<SVGPathElement>(null)
  const gap = useRef<SVGPathElement>(null)
  const plug = useRef<SVGCircleElement>(null)
  const lta = useRef<HTMLDivElement>(null)
  const done = useRef(onDone)
  useLayoutEffect(() => {
    done.current = onDone
  })

  useEffect(() => {
    let raf = 0
    let finished = false
    const finish = () => {
      if (finished) return
      finished = true
      cancelAnimationFrame(raf)
      done.current()
    }
    const t0 = performance.now()
    const frame = (now: number) => {
      const t = now - t0
      let curve = DANGLE
      if (t >= T_DRAG && t < T_SNAP) curve = mix(DANGLE, LIFT, inOut(clamp((t - T_DRAG) / (T_SNAP - T_DRAG))))
      else if (t >= T_SNAP) curve = mix(LIFT, PLUGGED, outBack(clamp((t - T_SNAP) / (T_HOLD - T_SNAP))))
      const path = d(curve)
      blue.current?.setAttribute('d', path)
      gap.current?.setAttribute('d', path)
      plug.current?.setAttribute('cx', String(curve[3][0]))
      plug.current?.setAttribute('cy', String(curve[3][1]))
      const plugR = t >= T_DRAG && t < T_SNAP ? 14.35 * (1 + 0.15 * Math.sin(Math.PI * clamp((t - T_DRAG) / (T_SNAP - T_DRAG)))) : 14.35
      plug.current?.setAttribute('r', String(plugR))

      const z = inOut(clamp((t - T_ZOOM) / (T_ZOOM_END - T_ZOOM)))
      const x = BIG.x + (SMALL.x - BIG.x) * z
      const y = BIG.y + (SMALL.y - BIG.y) * z
      const s = BIG.s + (SMALL.s - BIG.s) * z
      if (mark.current) mark.current.style.transform = `translate(${x}px, ${y}px) scale(${s})`
      if (lta.current) {
        lta.current.style.opacity = String(z)
        lta.current.style.transform = `translateX(${(1 - z) * 60}px)`
      }
      if (root.current) root.current.style.opacity = String(1 - clamp((t - T_FADE) / (T_END - T_FADE)))
      if (t >= T_END) finish()
      else raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)
    const skip = () => finish()
    window.addEventListener('keydown', skip)
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('keydown', skip)
    }
  }, [])

  return (
    <div className="intro" ref={root} onClick={() => done.current()} aria-label="Alta">
      <FitStage>
      <svg ref={mark} className="intro-mark" width={286.7} height={439.6} viewBox="0 0 286.7 439.6" overflow="visible" aria-hidden>
        <defs>
          <mask id="intro-gap" maskUnits="userSpaceOnUse" x={-200} y={-200} width={800} height={900}>
            <rect x={-200} y={-200} width={800} height={900} fill="#fff" />
            <path ref={gap} d={d(DANGLE)} fill="none" stroke="#000" strokeWidth={30} strokeLinecap="round" />
          </mask>
        </defs>
        {SQUARES.map(([x, y]) => (
          <rect key={`${x},${y}`} x={x} y={y} width={S} height={S} rx={9.57} fill="var(--ink)" />
        ))}
        <path d={ORANGE} mask="url(#intro-gap)" fill="none" stroke="var(--orange)" strokeWidth={20.8} strokeLinecap="round" />
        <circle cx={28.65} cy={181.55} r={14.35} fill="var(--orange)" />
        <circle cx={257.95} cy={257.95} r={14.35} fill="var(--orange)" />
        <path ref={blue} d={d(DANGLE)} fill="none" stroke="var(--blue)" strokeWidth={20.8} strokeLinecap="round" />
        <circle ref={plug} cx={DANGLE[3][0]} cy={DANGLE[3][1]} r={14.35} fill="var(--blue)" />
        <circle cx={28.6} cy={257.9} r={14.35} fill="var(--blue)" />
      </svg>
      <div ref={lta} className="intro-lta">lta</div>
      </FitStage>
    </div>
  )
}

/** The animation is drawn on the 1440 × 900 Figma frame; scale that frame to fit the window, centred. */
function FitStage({ children }: { children: ReactNode }) {
  const [fit, setFit] = useState({ s: 1, x: 0, y: 0 })
  useLayoutEffect(() => {
    const root = document.documentElement
    const resize = () => {
      const s = Math.min(root.clientWidth / 1440, root.clientHeight / 900)
      setFit({ s, x: (root.clientWidth - 1440 * s) / 2, y: (root.clientHeight - 900 * s) / 2 })
    }
    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(root)
    return () => ro.disconnect()
  }, [])
  return (
    <div className="intro-stage" style={{ transform: `translate(${fit.x}px, ${fit.y}px) scale(${fit.s})` }}>
      {children}
    </div>
  )
}
