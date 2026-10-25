// Small building blocks, one per Figma component (Button, StatusChip, Reading, Banner, StepNav v2,
// ProbeBadge, Logo/Wordmark, Schematic/Lab 1 + Lab 2). Styles in kit.css.

import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import type { Probe } from '../app/protocol'
import wordmark from '../assets/brand/wordmark.svg'
import bookInk from '../assets/figma/book-ink.svg'
import chevronInk from '../assets/figma/chevron-right-ink.svg'
import chevronPaper from '../assets/figma/chevron-right-paper.svg'
import circleCheck from '../assets/figma/circle-check.svg'
import dotGuide from '../assets/figma/dot-guide.svg'
import dotGuideNow from '../assets/figma/dot-guide-current.svg'
import dotOff from '../assets/figma/dot-off.svg'
import dotOk from '../assets/figma/dot-ok.svg'
import dotProblem from '../assets/figma/dot-problem.svg'
import lockInk from '../assets/figma/lock-ink40.svg'
import refresh24 from '../assets/figma/refresh-24.svg'
import lab1Done from '../assets/figma/schematic-lab1-done.svg'
import lab1Step1 from '../assets/figma/schematic-lab1-step1.svg'
import lab1Step2 from '../assets/figma/schematic-lab1-step2.svg'
import lab1Step3 from '../assets/figma/schematic-lab1-step3.svg'
import lab1Step4 from '../assets/figma/schematic-lab1-step4.svg'
import lab2Drawing from '../assets/figma/schematic-lab2.svg'
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
const DOT: Record<ChipStatus, string> = { ok: dotOk, problem: dotProblem, off: dotOff }

export function StatusChip({ label, status, title }: { label: string; status: ChipStatus; title?: string }) {
  return (
    <span className={`chip chip-${status}`} title={title}>
      <img src={DOT[status]} width={10} height={10} alt="" />
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
// Figma's Schematic/Lab 1: the part for the current step is blue, done parts ink, parts to come faint.

export type SchematicStep = 1 | 2 | 3 | 4 | 'done'

const LAB1_DRAWING: Record<string, string> = { 1: lab1Step1, 2: lab1Step2, 3: lab1Step3, 4: lab1Step4, done: lab1Done }
// [text, left, top, the step that adds it]
const LAB1_LABELS: [string, number, number, number][] = [
  ['+5 V', 4, 108, 1],
  ['row 6', 74, 40, 1],
  ['W1', 44, 92, 1],
  ['row 10', 180, 40, 2],
  ['R1 220 Ω', 118, 104, 2],
  ['row 13', 296, 40, 3],
  ['D1 LED', 230, 110, 3],
  ['GND', 402, 136, 4],
  ['W2', 352, 92, 4],
]
const LAB2_LABELS: [string, number, number, boolean][] = [
  ['+5 V', 4, 108, false],
  ['row 26', 66, 96, false],
  ['LDR1', 120, 116, false],
  ['OUT · row 30', 222, 10, true],
  ['R1 10 kΩ', 226, 104, false],
  ['row 34', 318, 96, false],
  ['GND', 402, 136, false],
]

export function Schematic({ labId, step, scale = 1, fallbackUrl }: { labId?: string; step: SchematicStep; scale?: number; fallbackUrl?: string | null }) {
  let body: ReactNode
  if (labId === 'lab1-led') {
    body = (
      <>
        <img className="schematic-drawing" src={LAB1_DRAWING[String(step)]} width={480} height={170} alt="Lab 1 schematic" />
        {LAB1_LABELS.map(([t, x, y, n]) => {
          const tone = step === 'done' || n < step ? 'done' : n === step ? 'now' : 'todo'
          return (
            <span key={t} className={`schematic-label sl-${tone}`} style={{ left: x, top: y }}>
              {t}
            </span>
          )
        })}
      </>
    )
  } else if (labId === 'lab2-light') {
    body = (
      <>
        <img className="schematic-drawing" src={lab2Drawing} width={480} height={170} alt="Lab 2 schematic" />
        {LAB2_LABELS.map(([t, x, y, blue]) => (
          <span key={t} className={`schematic-label ${blue ? 'sl-out' : 'sl-done'}`} style={{ left: x, top: y }}>
            {t}
          </span>
        ))}
      </>
    )
  } else if (fallbackUrl) {
    return <img src={fallbackUrl} alt="Schematic" style={{ maxWidth: 480 * scale, maxHeight: 170 * scale }} />
  } else {
    return null
  }
  return (
    <div className="schematic-box" style={{ width: 480 * scale, height: 170 * scale }}>
      <div className="schematic" style={{ transform: `scale(${scale})` }}>
        {body}
      </div>
    </div>
  )
}

/** A schematic that scales itself to its box (never above `max`): to the width, and with `fill` to the height too. */
export function FitSchematic({ max = 1, fill, ...props }: { labId?: string; step: SchematicStep; max?: number; fill?: boolean; fallbackUrl?: string | null }) {
  const ref = useRef<HTMLDivElement>(null)
  const [scale, setScale] = useState(max)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(() => setScale(Math.max(0.3, Math.min(max, el.clientWidth / 480, fill ? el.clientHeight / 170 : max))))
    ro.observe(el)
    return () => ro.disconnect()
  }, [max, fill])
  return (
    <div ref={ref} className={`schematic-fit${fill ? ' schematic-fill' : ''}`}>
      <Schematic {...props} scale={scale} />
    </div>
  )
}
