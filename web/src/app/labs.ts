// Lab data for the screens: the picker cards (#31) and the guide card's steps, split out of manual.md (#29).

import { useEffect, useState } from 'react'
import { parse } from 'yaml'
import type { Lab, LabPart } from './protocol'

export type LabCard = { id: string; title: string; chips: string[] }

/** The labs the server offers (`/labs`), each with its parts from the server's copy of lab.yaml. */
export function useLabCards(serverUp: boolean): LabCard[] {
  const [cards, setCards] = useState<LabCard[]>([])
  useEffect(() => {
    if (!serverUp) return
    let cancelled = false
    fetch('/labs')
      .then((r) => r.json())
      .then((list: { id: string; title: string }[]) =>
        Promise.all(
          list.map(async ({ id, title }) => {
            const parts = await fetch(`/labs/${id}/lab.yaml`)
              .then((r) => (r.ok ? r.text() : ''))
              .then((src) => ((parse(src) as Lab | null)?.parts ?? []))
              .catch(() => [])
            return { id, title, chips: parts.map(partLabel) }
          }),
        ),
      )
      .then((c) => !cancelled && setCards(c))
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [serverUp])
  return cards
}

/** "Lab 1 · Light an LED" → "Lab 1: Light an LED" (how titles read on screen). */
export function labTitle(title: string): string {
  return title.replace(/\s*·\s*/, ': ')
}

export function partLabel(p: LabPart): string {
  switch (p.kind) {
    case 'wire':
      return `${p.ref} ${p.color ?? ''} wire`.replace('  ', ' ')
    case 'resistor':
      return `${p.ref} ${ohms(p.value_ohm)}`
    case 'led':
      return `${p.ref} ${p.color ?? ''} LED`.replace('  ', ' ')
    case 'ldr':
    case 'photoresistor':
      return `${p.ref} photoresistor`
    default:
      return `${p.ref} ${p.kind}`
  }
}

export function ohms(v?: number): string {
  if (v === undefined) return ''
  if (v >= 1_000_000) return `${v / 1_000_000} MΩ`
  if (v >= 1000) return `${v / 1000} kΩ`
  return `${v} Ω`
}

// ---------- manual.md → guide steps ----------

export type GuideStep = { n: number; title: string; text: string }

/** Plain text: drop **bold**, *italics* and `code` markers. */
export function plain(md: string): string {
  return md.replace(/\*\*(.+?)\*\*/g, '$1').replace(/\*(.+?)\*/g, '$1').replace(/`(.+?)`/g, '$1').trim()
}

/** The numbered steps: each `## Step N — Title` section, its instructions joined into one line. */
export function manualSteps(md: string): GuideStep[] {
  const out: GuideStep[] = []
  const re = /^## Step (\d+)\s*[—–-]\s*(.+)$/gm
  const heads = [...md.matchAll(re)]
  heads.forEach((h, i) => {
    const start = (h.index ?? 0) + h[0].length
    const end = i + 1 < heads.length ? heads[i + 1].index : md.indexOf('\n## ', start)
    const body = md.slice(start, end === -1 ? undefined : end)
    const items = body
      .split('\n')
      .map((l) => l.match(/^\s*(?:\d+\.|[-*])\s+(.*)$/)?.[1])
      .filter((l): l is string => !!l)
    out.push({ n: Number(h[1]), title: h[2].trim(), text: plain(items.join(' ')) })
  })
  return out
}

/** The setup instruction before Step 1 ("Before you start, plug the pod's red wire…"). */
export function setupText(md: string): string {
  const m = md.match(/Before you start,?\s*([^\n]+)/)
  if (!m) return ''
  const t = plain(m[1])
  return t.charAt(0).toUpperCase() + t.slice(1)
}

/** Steps for the guide card: manual sections first, lab.yaml titles as the fallback. */
export function guideSteps(lab: Lab | null): GuideStep[] {
  if (!lab) return []
  const fromManual = lab.manual_md ? manualSteps(lab.manual_md) : []
  if (fromManual.length) return fromManual
  return (lab.steps ?? []).map((s) => ({ n: s.n, title: s.title, text: '' }))
}

/** "10c" → "row 10", "10:a-e" → "row 10", "rail:a+" → "+ rail". */
export function whereLabel(at?: string): string {
  if (!at) return ''
  const rail = at.match(/^rail:[aj]([+-])$/)
  if (rail) return `${rail[1] === '+' ? '+' : '−'} rail`
  const row = at.match(/^(\d+)/)
  return row ? `row ${row[1]}` : at
}

/** The strip a hole sits in ("10c" → "10:a-e"), for the expect highlight. */
export function stripOf(at: string): string {
  const m = at.match(/^(\d+)([a-j])$/)
  if (!m) return at
  return `${m[1]}:${'abcde'.includes(m[2]) ? 'a-e' : 'f-j'}`
}
