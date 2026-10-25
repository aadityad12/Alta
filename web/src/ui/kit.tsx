// Small building blocks, one per Figma component (Button, StatusChip, Reading, Banner, StepNav v2,
// ProbeBadge, Logo/Wordmark, Schematic/Lab 1 + Lab 2), plus the bench's probe readings row. Styles in kit.css.

import { useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { PROBE_NAME, PROBES, type Probe } from '../app/protocol'
import lab1Svg from '../../../labs/lab1-led/schematic.svg?raw'
import lab2Svg from '../../../labs/lab2-light/schematic.svg?raw'
import wordmark from '../assets/brand/wordmark.svg'
import bookInk from '../assets/figma/book-ink.svg'
import chevronInk from '../assets/figma/chevron-right-ink.svg'
import chevronPaper from '../assets/figma/chevron-right-paper.svg'
import circleCheck from '../assets/figma/circle-check.svg'
import dotGuide from '../assets/figma/dot-guide.svg'
import dotGuideNow from '../assets/figma/dot-guide-current.svg'
import lockInk from '../assets/figma/lock-ink40.svg'
import refresh24 from '../assets/figma/refresh-24.svg'
import unplug from '../assets/figma/unplug.svg'
import wifiOff from '../assets/figma/wifi-off.svg'
import './kit.css'

// ---------- Button ----------

type ButtonProps = {
  kind?: 'primary' | 'secondary' | 'ghost' | 'locked' | 'danger'
  chevron?: boolean
  icon?: string
  big?: boolean
  onClick?: () => void
  title?: string
  children: ReactNode
}

export function Button({ kind = 'primary', chevron, icon, big, onClick, title, children }: ButtonProps) {
  const locked = kind === 'locked'
  return (
    <button type="button" className={`btn btn-${kind}${big ? ' btn-big' : ''}`} onClick={locked ? undefined : onClick} aria-disabled={locked || undefined} title={title}>
      {locked && <img src={lockInk} width={20} height={20} alt="" />}
      {icon && <img src={icon} width={22} height={22} alt="" />}
      {children}
      {chevron && !locked && <img src={kind === 'primary' || kind === 'danger' ? chevronPaper : chevronInk} width={20} height={20} alt="" />}
    </button>
  )
}

// ---------- StatusChip ----------

export type ChipStatus = 'ok' | 'problem' | 'off'

export function StatusChip({ label, status, title }: { label: string; status: ChipStatus; title?: string }) {
  return (
    <span className={`chip chip-${status}`} title={title}>
      <span className="chip-dot" aria-hidden />
      <span className="t-label">{label}</span>
    </span>
  )
}

// ---------- Logo / header ----------

export function Wordmark() {
  return <img className="wordmark" src={wordmark} width={75.56} height={32} alt="Alta" />
}

export function BookButton({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" className="round-btn" onClick={onClick} title="Lab manual (M)" aria-label="Open the lab manual">
      <img src={bookInk} width={22} height={22} alt="" />
    </button>
  )
}

export function Header({ title, children, padded }: { title?: string; children?: ReactNode; padded?: boolean }) {
  return (
    <header className={`app-header${padded ? ' app-header-wide' : ''}`}>
      <Wordmark />
      {title && (
        <>
          <span className="header-divider" />
          <h1 className="t-h3 header-title">{title}</h1>
        </>
      )}
      <span className="spacer" />
      {children}
    </header>
  )
}

// ---------- ProbeBadge + Reading ----------

export function ProbeBadge({ probe }: { probe: Probe }) {
  return (
    <span className={`probe-badge probe-${probe}`}>
      <span className="t-label">{probe}</span>
    </span>
  )
}

export type ReadingTone = 'waiting' | 'bad' | 'good'

export function Reading({ probe, where, value, status, tone }: { probe: Probe; where: string; value: string; status: string; tone: ReadingTone }) {
  return (
    <div className="reading">
      <ProbeBadge probe={probe} />
      <div className="reading-text">
        <span className="t-body c-60">{where}</span>
        <span className="t-reading">{value}</span>
      </div>
      <span className={`pill pill-${tone} t-label`}>{status}</span>
    </div>
  )
}

// ---------- Probe readings: all four probes, each on a 0–5 V bar (ALTA's expected range in blue) ----------

const FULL_MV = 5000

export type ProbeAsk = { where: string; expected_mv?: number; tol_mv?: number }

export function ProbeReadings({ mv, asked, paused }: { mv?: number[]; asked: Partial<Record<Probe, ProbeAsk>>; paused?: boolean }) {
  const pct = (x: number) => Math.max(0, Math.min(100, (x / FULL_MV) * 100))
  const volts = (x: number) => (x / 1000).toFixed(2)
  return (
    <div className="probe-readings">
      {PROBES.map((p, i) => {
        const v = mv?.[i]
        const a = asked[p]
        const live = !paused && v !== undefined && v >= 0
        const value = paused || v === undefined ? '—' : v < 0 ? '– –' : `${volts(v)} V`
        const tol = a?.tol_mv ?? 250
        const range = a?.expected_mv !== undefined ? [a.expected_mv - tol, a.expected_mv + tol] : null
        return (
          <div key={p} className={`probe-card probe-card-${p}${a ? ' probe-card-asked' : ''}`}>
            <div className="probe-card-head">
              <ProbeBadge probe={p} />
              <span className="t-body probe-name">{PROBE_NAME[p]}</span>
              <span className="spacer" />
              <span className="c-60 probe-where">{a?.where || '–'}</span>
            </div>
            <div className="probe-value-box">
              <span className={`probe-value${live ? '' : ' c-40'}`}>{value}</span>
            </div>
            <div className="probe-bar">
              {range && <span className="probe-band" style={{ left: `${pct(range[0])}%`, width: `${pct(range[1]) - pct(range[0])}%` }} />}
              {live && <span className="probe-needle" style={{ left: `${pct(v)}%` }} />}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ---------- Step boxes: the guide's progress, 1 … n joined by a line (done ink, current blue) ----------

export function StepBoxes({ total, current }: { total: number; current: number }) {
  return (
    <ol className="step-boxes" aria-label={current ? `Step ${current} of ${total}` : 'Setup'}>
      {Array.from({ length: total }, (_, i) => {
        const n = i + 1
        const tone = n < current ? 'done' : n === current ? 'now' : 'todo'
        return (
          <li key={n} className={`step-box step-box-${tone}`}>
            {n}
          </li>
        )
      })}
    </ol>
  )
}

// ---------- Banner ----------

const BANNER_ICON = { unplug, 'wifi-off': wifiOff, refresh: refresh24, check: circleCheck }

export function Banner({ icon, title, body, action, onAction }: { icon: keyof typeof BANNER_ICON; title: string; body: string; action?: string; onAction?: () => void }) {
  return (
    <div className="banner" role="status">
      <img src={BANNER_ICON[icon]} width={24} height={24} alt="" />
      <div className="banner-text">
        <span className="t-label">{title}</span>
        <span className="t-body banner-body">{body}</span>
      </div>
      {action && (
        <Button kind="secondary" onClick={onAction}>
          {action}
        </Button>
      )}
    </div>
  )
}

// ---------- StepNav v2 ----------

export type NavState = 'locked' | 'confirmed' | 'setup' | 'last'

export function StepNav({ state, onBack, onNext }: { state: NavState; onBack: () => void; onNext: () => void }) {
  const label = state === 'last' ? 'Finish' : state === 'setup' ? 'Done' : 'Next'
  return (
    <div className="step-nav">
      <Button kind="secondary" onClick={onBack}>
        Back
      </Button>
      <Button kind={state === 'locked' ? 'locked' : 'primary'} chevron onClick={onNext} title={state === 'locked' ? 'Unlocks when ALTA confirms this step' : undefined}>
        {label}
      </Button>
    </div>
  )
}

// ---------- Guide progress dots ----------

export function GuideDots({ total, current }: { total: number; current: number }) {
  return (
    <span className="guide-dots" aria-label={`Step ${current} of ${total}`}>
      {Array.from({ length: total }, (_, i) => {
        const n = i + 1
        if (n === current) return <img key={n} src={dotGuideNow} width={10} height={10} alt="" />
        if (n < current) return <img key={n} src={dotGuide} width={8} height={8} alt="" />
        return <span key={n} className="guide-dot-todo" />
      })}
    </span>
  )
}

// ---------- Schematics ----------
// The labs' own schematic.svg (labs/<lab>/schematic.svg), recoloured by step: the part for the current
// step is blue, done parts ink, parts to come light grey.

export type SchematicStep = 1 | 2 | 3 | 4 | 'done'

// the drawing's area inside the 700 × 430 SVG (its white margin trimmed)
const SCH = { x: 10, y: 14, w: 660, h: 390 }

// the step that adds each piece: per <g id>, one step for the whole group or one per child;
// `labels` is the labels group's paths in document order
type StepMap = { groups: Record<string, number | number[]>; labels: number[] }
const LAB_SCHEMATICS: Record<string, { svg: string; steps: StepMap }> = {
  'lab1-led': {
    svg: lab1Svg,
    steps: {
      groups: { supply: 1, n_5v: 1, 'r1-body': 2, n_led_anode: 3, 'd1-body': 3, n_led_cathode: 3, W2: 4, n_gnd: 4 },
      // +5 V, (pod), GND, R1, 220 Ω, D1, Red LED, row 6, row 10, row 13
      labels: [1, 1, 4, 2, 2, 3, 3, 1, 2, 3],
    },
  },
  'lab2-light': {
    svg: lab2Svg,
    steps: {
      // n_out: the wire down to R1 comes with R1; the OUT stub, node dot and terminal with step 4
      groups: { supply: 1, n_5v: 1, 'ldr1-body': 2, n_out: [3, 4, 4, 4], 'r1-body': 3, n_gnd: 3 },
      // +5 V, (pod), GND, LDR1, light sensor, OUT, row 26, row 30, R1, 10 kΩ, row 34
      labels: [1, 1, 3, 2, 2, 4, 1, 2, 3, 3, 3],
    },
  },
}

/** The SVG markup with each piece classed sch-done / sch-now / sch-todo for this step. */
function paintSchematic(svg: string, { groups, labels }: StepMap, step: SchematicStep): string {
  const doc = new DOMParser().parseFromString(svg, 'image/svg+xml')
  const root = doc.documentElement
  root.querySelector(':scope > rect')?.remove() // the white backdrop: let the card's colour show
  root.setAttribute('viewBox', `${SCH.x} ${SCH.y} ${SCH.w} ${SCH.h}`)
  root.setAttribute('width', '100%')
  root.setAttribute('height', '100%')
  root.setAttribute('class', 'schematic-svg')
  const tone = (n: number) => (step === 'done' || n < step ? 'sch-done' : n === step ? 'sch-now' : 'sch-todo')
  for (const g of Array.from(root.querySelectorAll('g[id]'))) {
    const n = g.id === 'labels' ? labels : groups[g.id]
    if (n === undefined) continue
    Array.from(g.children).forEach((el, i) => {
      const s = typeof n === 'number' ? n : n[i]
      if (s !== undefined) el.setAttribute('class', tone(s))
    })
  }
  return root.outerHTML
}

export function Schematic({ labId, step, scale = 1, fallbackUrl }: { labId?: string; step: SchematicStep; scale?: number; fallbackUrl?: string | null }) {
  const lab = labId ? LAB_SCHEMATICS[labId] : undefined
  const html = useMemo(() => (lab ? paintSchematic(lab.svg, lab.steps, step) : ''), [lab, step])
  if (!lab) return fallbackUrl ? <img src={fallbackUrl} alt="Schematic" style={{ maxWidth: SCH.w * scale, maxHeight: SCH.h * scale }} /> : null
  return <div className="schematic-box" role="img" aria-label="Circuit schematic" style={{ width: SCH.w * scale, height: SCH.h * scale }} dangerouslySetInnerHTML={{ __html: html }} />
}

/** A schematic that scales itself to its box (never above `max`): to the width, and with `fill` to the height too. */
export function FitSchematic({ max = 1, fill, ...props }: { labId?: string; step: SchematicStep; max?: number; fill?: boolean; fallbackUrl?: string | null }) {
  const ref = useRef<HTMLDivElement>(null)
  const [scale, setScale] = useState(max)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(() => setScale(Math.max(0.3, Math.min(max, el.clientWidth / SCH.w, fill ? el.clientHeight / SCH.h : max))))
    ro.observe(el)
    return () => ro.disconnect()
  }, [max, fill])
  return (
    <div ref={ref} className={`schematic-fit${fill ? ' schematic-fill' : ''}`}>
      <Schematic {...props} scale={scale} />
    </div>
  )
}
