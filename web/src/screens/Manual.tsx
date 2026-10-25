// The full lab manual (Figma "Manual / Lab 1 (full)"): manual.md rendered whole, never shortened.
// A tiny Markdown reader covers what the manuals use: headings, paragraphs, lists, tables, code.

import { useEffect, useMemo, useRef, type ReactNode } from 'react'
import bookBlue from '../assets/figma/book-blue.svg'
import xInk from '../assets/figma/x-ink.svg'
import './screens.css'

type Block =
  | { k: 'h'; level: number; text: string }
  | { k: 'p'; text: string }
  | { k: 'ol' | 'ul'; items: string[] }
  | { k: 'table'; head: string[]; rows: string[][] }
  | { k: 'code'; text: string }

const BLOCK_START = /^(#{1,6}\s|\s*\||\s*\d+\.\s|\s*[-*]\s|```)/

function parseBlocks(md: string): Block[] {
  const lines = md.replace(/\r/g, '').split('\n')
  const out: Block[] = []
  let i = 0
  while (i < lines.length) {
    const l = lines[i]
    if (!l.trim() || /^---+\s*$/.test(l)) {
      i++
      continue
    }
    if (l.startsWith('```')) {
      const buf: string[] = []
      i++
      while (i < lines.length && !lines[i].startsWith('```')) buf.push(lines[i++])
      i++
      out.push({ k: 'code', text: buf.join('\n') })
      continue
    }
    const h = l.match(/^(#{1,6})\s+(.*)$/)
    if (h) {
      out.push({ k: 'h', level: h[1].length, text: h[2] })
      i++
      continue
    }
    if (/^\s*\|/.test(l)) {
      const rows: string[][] = []
      while (i < lines.length && /^\s*\|/.test(lines[i])) {
        const cells = lines[i++].trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim())
        if (!cells.every((c) => /^:?-{2,}:?$/.test(c))) rows.push(cells)
      }
      out.push({ k: 'table', head: rows[0] ?? [], rows: rows.slice(1) })
      continue
    }
    const ordered = /^\s*\d+\.\s/.test(l)
    if (ordered || /^\s*[-*]\s/.test(l)) {
      const listRe = ordered ? /^\s*\d+\.\s+/ : /^\s*[-*]\s+/
      const items: string[] = []
      while (i < lines.length && listRe.test(lines[i])) items.push(lines[i++].replace(listRe, ''))
      out.push({ k: ordered ? 'ol' : 'ul', items })
      continue
    }
    const buf = [l]
    i++
    while (i < lines.length && lines[i].trim() && !BLOCK_START.test(lines[i])) buf.push(lines[i++])
    out.push({ k: 'p', text: buf.join(' ') })
  }
  return out
}

function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/g).map((p, i) => {
    if (p.startsWith('**') && p.endsWith('**') && p.length > 4) return <strong key={i}>{p.slice(2, -2)}</strong>
    if (p.startsWith('`') && p.endsWith('`') && p.length > 2) return <code key={i}>{p.slice(1, -1)}</code>
    if (p.startsWith('*') && p.endsWith('*') && p.length > 2) return <em key={i}>{p.slice(1, -1)}</em>
    return p
  })
}

const isFormula = (t: string) => !t.includes('**') && t.length < 70 && / = /.test(t) && !/[.:]$/.test(t)

function renderBlock(b: Block, i: number): ReactNode {
  switch (b.k) {
    case 'h': {
      if (b.level === 1) return null
      const step = b.text.match(/^Step (\d+)/)
      const text = b.text.replace(/\s+[—–]\s+/, ' · ')
      return b.level === 2 ? (
        <h2 key={i} className="t-h2 m-h2" id={step ? `step-${step[1]}` : slug(b.text)}>
          {text}
        </h2>
      ) : (
        <h3 key={i} className="t-h3 m-h3">
          {text}
        </h3>
      )
    }
    case 'p':
      if (b.text.startsWith('**Check:**'))
        return (
          <p key={i} className="t-body-l m-check">
            {inline(b.text)}
          </p>
        )
      if (isFormula(b.text))
        return (
          <p key={i} className="t-caption m-formula">
            {b.text}
          </p>
        )
      return (
        <p key={i} className="t-body-l">
          {inline(b.text)}
        </p>
      )
    case 'ol':
      return (
        <ol key={i} className="m-ol">
          {b.items.map((it, j) => (
            <li key={j}>
              <span className="m-num t-strong">{j + 1}</span>
              <span className="t-body-l">{inline(it)}</span>
            </li>
          ))}
        </ol>
      )
    case 'ul':
      return (
        <ul key={i} className="m-ul">
          {b.items.map((it, j) => (
            <li key={j} className="t-body-l">
              {inline(it)}
            </li>
          ))}
        </ul>
      )
    case 'table': {
      const wide = b.head.length >= 4 ? b.head.length - 1 : -1 // the last of 4+ columns gets the room
      const cells = (row: string[], head: boolean) =>
        row.map((c, j) => (
          <span key={j} style={{ flex: j === wide ? '2 0 0' : '1 0 0' }} className={head ? 't-strong' : 't-body'}>
            {inline(c)}
          </span>
        ))
      return (
        <div key={i} className="m-table" role="table">
          <div className="m-tr m-th" role="row">
            {cells(b.head, true)}
          </div>
          {b.rows.map((r, j) => (
            <div key={j} className="m-tr" role="row">
              {cells(r, false)}
            </div>
          ))}
        </div>
      )
    }
    case 'code': {
      // "+5 V rail ──W1── row 6 ──R1── …": nodes and parts as pills, like the Figma "current path"
      if (b.text.includes('──')) {
        const parts = b.text.split(/─{2,}/).map((s) => s.trim()).filter(Boolean)
        return (
          <div key={i} className="m-path">
            {parts.map((p, j) => (
              <span key={j} className="m-path-step">
                {j > 0 && <span className="t-strong c-60">→</span>}
                <span className={`m-pill t-strong${j % 2 ? ' m-pill-part' : ''}`}>{p}</span>
              </span>
            ))}
          </div>
        )
      }
      return (
        <pre key={i} className="m-pre">
          {b.text}
        </pre>
      )
    }
  }
}

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, '-')

type Props = {
  title: string
  md: string
  focus?: string // section id to open at
  onClose: () => void
}

/** A pop-up over the bench, the screen behind blurred and a little faded. */
export function ManualPage({ title, md, focus, onClose }: Props) {
  const blocks = useMemo(() => parseBlocks(md), [md])
  const bodyRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!focus) return
    const el = bodyRef.current?.querySelector<HTMLElement>(`#${focus}`)
    if (el && bodyRef.current) bodyRef.current.scrollTop = el.offsetTop - 24
  }, [focus])
  return (
    <div className="manual-layer" onClick={onClose}>
      <div className="manual-modal" role="dialog" aria-label="Lab manual" onClick={(e) => e.stopPropagation()}>
        <header className="manual-head">
          <div className="manual-brand">
            <img src={bookBlue} width={28} height={28} alt="" />
            <div className="manual-title">
              <span className="t-label c-blue">Lab manual</span>
              <h1 className="t-h2">{title}</h1>
            </div>
          </div>
          <span className="spacer" />
          <button type="button" className="close-btn" onClick={onClose} aria-label="Close the manual (Esc)">
            <img src={xInk} width={22} height={22} alt="" />
          </button>
        </header>
        <div className="manual-body" ref={bodyRef}>
          <article className="manual-column">{blocks.map(renderBlock)}</article>
        </div>
      </div>
    </div>
  )
}
