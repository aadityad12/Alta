// The smaller screens: A1 Pick a lab, B12 Guide complete · good luck, C4 Reconnecting, C7 ALTA can't
// help, plus the new-student confirm and the shortcut cheat-sheet (#31).

import type { ComponentProps, ReactNode } from 'react'
import { labTitle, type LabCard } from '../app/labs'
import bookPaper from '../assets/figma/book-paper.svg'
import refresh40 from '../assets/figma/refresh-40.svg'
import terminal from '../assets/figma/terminal.svg'
import userOrange from '../assets/figma/user-round-orange.svg'
import { ChatDock } from '../ui/Chat'
import { Button, FitSchematic, Header } from '../ui/kit'
import './screens.css'

export function Picker({ cards, chips, onStart }: { cards: LabCard[]; chips: ReactNode; onStart: (id: string) => void }) {
  return (
    <div className="screen screen-wide picker">
      <Header padded>{chips}</Header>
      <div className="picker-content">
        <h1 className="t-h1">Pick a lab</h1>
        <div className="lab-cards">
          {cards.map((c) => (
            <article key={c.id} className="lab-card">
              <div className="lab-card-art">
                <FitSchematic fill labId={c.id} step="done" max={0.8} />
              </div>
              <div className="lab-card-details">
                <h2 className="t-h2">{labTitle(c.title)}</h2>
                <div className="part-chips">
                  {c.chips.map((p) => (
                    <span key={p} className="part-chip t-body">
                      {p}
                    </span>
                  ))}
                </div>
                <span className="spacer" />
                <div>
                  <Button chevron onClick={() => onStart(c.id)}>
                    Start lab
                  </Button>
                </div>
              </div>
            </article>
          ))}
        </div>
      </div>
    </div>
  )
}

type DoneProps = {
  title: string
  labId: string
  headerRight: ReactNode
  dock: ComponentProps<typeof ChatDock>
  onManual: () => void
  onLabs: () => void
  onNewStudent: () => void
}

export function GoodLuck({ title, labId, headerRight, dock, onManual, onLabs, onNewStudent }: DoneProps) {
  return (
    <div className="screen bench good-luck">
      <Header title={title}>{headerRight}</Header>
      <div className="good-luck-body">
        <div className="finished-circuit">
          <FitSchematic labId={labId} step="done" />
        </div>
        <span className="gap-6" />
        <h2 className="t-h1">Your circuit is built</h2>
        <p className="t-body-l c-60 good-luck-lead">
          Good luck with your lab measurements! Open the manual to see what to measure and calculate, then write your results in your notebook.
        </p>
        <div className="good-luck-actions">
          <Button big icon={bookPaper} onClick={onManual}>
            Open the manual
          </Button>
          <Button big kind="secondary" onClick={onLabs}>
            Back to labs
          </Button>
        </div>
      </div>
      <div className="new-student">
        <Button kind="ghost" onClick={onNewStudent} title="New student (N)">
          New student
        </Button>
      </div>
      <ChatDock {...dock} />
    </div>
  )
}

export function Reconnecting({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="veil" role="alertdialog" aria-label="Reconnecting">
      <div className="card reconnecting">
        <img className="spin" src={refresh40} width={40} height={40} alt="" />
        <h2 className="t-h2">Reconnecting to ALTA…</h2>
        <p className="t-body-l c-60">Lost the connection to the bench server. Trying again…</p>
        <span className="gap-6" />
        <p className="t-body c-60">Not back after a minute? Restart the server:</p>
        <code className="code-chip t-label">
          <img src={terminal} width={18} height={18} alt="" />
          scripts/dev.sh
        </code>
        <Button onClick={onRetry}>Retry now</Button>
      </div>
    </div>
  )
}

export function CantHelp({ chips, onRetry }: { chips: ReactNode; onRetry: () => void }) {
  return (
    <div className="screen cant-help">
      <Header>{chips}</Header>
      <div className="cant-help-body">
        <span className="cant-help-icon">
          <img src={userOrange} width={40} height={40} alt="" />
        </span>
        <h1 className="t-h1">ALTA can't help right now</h1>
        <p className="t-body-l c-60">Please ask a TA to check this bench. Your circuit is fine to leave as it is.</p>
        <div className="pt-8">
          <Button kind="secondary" onClick={onRetry}>
            Try again
          </Button>
        </div>
      </div>
    </div>
  )
}

export function ConfirmNewStudent({ onCancel, onConfirm }: { onCancel: () => void; onConfirm: () => void }) {
  return (
    <div className="veil" role="alertdialog" aria-label="New student">
      <div className="card confirm">
        <h2 className="t-h2">Start fresh for a new student?</h2>
        <p className="t-body-l c-60">This clears the chat and the steps. The board calibration stays.</p>
        <div className="confirm-actions">
          <Button kind="secondary" onClick={onCancel}>
            Cancel
          </Button>
          <Button onClick={onConfirm}>New student</Button>
        </div>
      </div>
    </div>
  )
}

const KEYS: [string, string][] = [
  ['Space', 'Hold to talk to ALTA'],
  ['/', 'Type a question (when it’s too loud)'],
  ['M', 'Open the lab manual'],
  ['R', 'Recalibrate the board'],
  ['N', 'New student'],
  ['Esc', 'Close'],
]

export function Shortcuts({ onClose }: { onClose: () => void }) {
  return (
    <div className="veil" onClick={onClose} role="dialog" aria-label="Keyboard shortcuts">
      <div className="card shortcuts" onClick={(e) => e.stopPropagation()}>
        <h2 className="t-h2">Shortcuts</h2>
        {KEYS.map(([k, what]) => (
          <div key={k} className="shortcut">
            <kbd className="t-label">{k}</kbd>
            <span className="t-body-l">{what}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
