// ChatDock (bottom), the chat panel beside the camera on the bench, and the pulled-up chat sheet (#29).
// Caption = the latest line; hold the mic (or Space) to talk; `/` focuses the typed fallback (#31).

import { useEffect, useRef, type RefObject } from 'react'
import { PROBE_NAME, type Line, type Probe } from '../app/protocol'
import chevronDown from '../assets/figma/chevron-down-paper.svg'
import micMuted from '../assets/figma/mic-muted.svg'
import micPaper from '../assets/figma/mic-paper.svg'
import send from '../assets/figma/send.svg'
import './chat.css'

export type DockState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'typing' | 'offline'

type InputProps = {
  dock: DockState
  draft: string
  setDraft: (s: string) => void
  onSend: () => void
  inputRef: RefObject<HTMLInputElement | null>
  micDisabled?: boolean
  micTitle?: string
  onTalk: (down: boolean) => void
  onFocusChange: (focused: boolean) => void
  placeholder?: string
}

function InputRow({ dock, draft, setDraft, onSend, inputRef, micDisabled, micTitle, onTalk, onFocusChange, placeholder = 'Type here…' }: InputProps) {
  const holding = useRef(false)
  const up = () => {
    if (!holding.current) return
    holding.current = false
    onTalk(false)
  }
  const muted = dock === 'thinking' || dock === 'typing' || dock === 'offline'
  return (
    <div className="input-row">
      <label className="type-here">
        <input
          ref={inputRef}
          className="t-body-l"
          value={draft}
          placeholder={placeholder}
          onChange={(e) => setDraft(e.target.value)}
          onFocus={() => onFocusChange(true)}
          onBlur={() => onFocusChange(false)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && draft.trim()) onSend()
            if (e.key === 'Escape') e.currentTarget.blur()
          }}
        />
        {dock === 'typing' && (
          <button type="button" className="send" onMouseDown={(e) => e.preventDefault()} onClick={onSend} aria-label="Send" disabled={!draft.trim()}>
            <img src={send} width={18} height={18} alt="" />
          </button>
        )}
      </label>
      {dock === 'listening' ? (
        <button type="button" className="recording" onPointerUp={up} onPointerCancel={up} aria-label="Release to send">
          <span className="voice-bars" aria-hidden>
            {[11.2, 20.8, 32, 22.4, 27.2, 17.6, 14.4].map((h, i) => (
              <i key={i} style={{ height: h, animationDelay: `${i * -0.13}s` }} />
            ))}
          </span>
        </button>
      ) : (
        <button
          type="button"
          className={`mic${muted ? ' mic-muted' : ''}`}
          disabled={micDisabled}
          title={micTitle ?? 'Hold to talk (or hold Space)'}
          aria-label="Hold to talk"
          onPointerDown={(e) => {
            if (micDisabled || e.button !== 0) return
            holding.current = true
            onTalk(true)
            // the button swaps to the recording pill mid-press, so listen for the release on the window too
            window.addEventListener('pointerup', up, { once: true })
          }}
          onPointerUp={up}
          onPointerCancel={up}
        >
          <img src={muted ? micMuted : micPaper} width={24} height={24} alt="" />
        </button>
      )}
    </div>
  )
}

type DockProps = InputProps & {
  tag: string
  tagTone: 'blue' | 'muted' | 'orange'
  caption: string
  italic?: boolean
  muted?: boolean // a how-to hint, not a line from the conversation
  onPullUp: () => void
}

export function ChatDock({ tag, tagTone, caption, italic, muted, onPullUp, ...input }: DockProps) {
  return (
    <section className="dock" aria-label="Chat with ALTA">
      <button type="button" className="handle" onClick={onPullUp} aria-label="Pull up the full chat">
        <span />
      </button>
      <div className="caption" onClick={onPullUp}>
        {tag && <span className={`t-label tag tag-${tagTone}`}>{tag}</span>}
        <p className={`t-caption${input.dock === 'thinking' || muted ? ' dim' : ''}${italic ? ' live' : ''}`} aria-live="polite">
          {caption}
        </p>
      </div>
      <InputRow {...input} />
    </section>
  )
}

/** A scroll box that jumps to the newest line whenever the lines change. */
function useStickToBottom(lines: Line[]) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight })
  }, [lines])
  return ref
}

function Messages({ lines }: { lines: Line[] }) {
  const listRef = useStickToBottom(lines)
  return (
    <div className="messages" ref={listRef}>
      {lines.length === 0 && <p className="t-body-l msg-empty">Nothing yet. Hold the mic or press / to ask ALTA something.</p>}
      {lines.map((l, i) => (
        <div key={i} className={`msg msg-${l.role}`}>
          <p className={`t-caption bubble${l.final ? '' : ' live'}`}>{l.text}</p>
        </div>
      ))}
    </div>
  )
}

const PROBE_BY_NAME = Object.fromEntries(Object.entries(PROBE_NAME).map(([p, name]) => [name, p as Probe]))

/** A system line ("Yellow reads 5.00 V in row 6 ✓"): a dashed box, with the probe's colour dot when it names one. */
function SystemLine({ text }: { text: string }) {
  const probe = PROBE_BY_NAME[text.split(' ')[0]]
  return (
    <div className="tr-system">
      {probe && <span className={`tr-dot probe-${probe}`} aria-hidden />}
      <span className="t-body">{text}</span>
    </div>
  )
}

type PanelProps = InputProps & { lines: Line[] }

/** The transcript beside the live camera on the bench: the whole conversation, always open. */
export function ChatPanel({ lines, ...input }: PanelProps) {
  const listRef = useStickToBottom(lines)
  return (
    <section className="chat-panel" aria-label="Transcript">
      <div className="transcript" ref={listRef}>
        {lines.length === 0 && <p className="t-body-l msg-empty">Nothing yet. Hold the mic or press / to ask ALTA something.</p>}
        {lines.map((l, i) =>
          l.role === 'system' ? (
            <SystemLine key={i} text={l.text} />
          ) : (
            <div key={i} className="tr-line">
              <span className={`t-label tr-tag tr-tag-${l.role}`}>{l.role === 'bench' ? 'ALTA' : 'YOU'}</span>
              <p className={`tr-text${l.final ? '' : ' live'}`}>{l.text}</p>
            </div>
          ),
        )}
      </div>
      <div className="tr-input">
        <span className="t-body tr-hint">Hold the mic or press / to ask</span>
        <InputRow {...input} placeholder="Type to ALTA…" />
      </div>
    </section>
  )
}

type SheetProps = InputProps & { lines: Line[]; onClose: () => void }

export function ChatSheet({ lines, onClose, ...input }: SheetProps) {
  return (
    <div className="sheet-layer">
      <div className="sheet-dim" onClick={onClose} />
      <section className="sheet" aria-label="Chat">
        <span className="sheet-handle" />
        <div className="sheet-head">
          <h2 className="t-h3">Chat</h2>
          <span className="spacer" />
          <button type="button" className="sheet-close" onClick={onClose} aria-label="Close the chat">
            <img src={chevronDown} width={26} height={26} alt="" />
          </button>
        </div>
        <Messages lines={lines} />
        <InputRow {...input} />
      </section>
    </div>
  )
}
