// ALTA student screen (#28–#31): intro → pick a lab → read the manual → at the bench → good luck.
// Calibration is its own screen (the banner or R). Responsive: matches the Figma frames at
// 1440 × 900, reflows below that, and stacks on narrow screens (screens.css).

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { captureAnnotatedFrame, loadCalibration, saveCalibration, type Calibration, type OverlayItem } from './board'
import { guideSteps, labTitle, setupText, stripOf, useLabCards, whereLabel } from './app/labs'
import { PROBE_NAME, type ClientMsg, type Health, type Lab, type Part, type Probe } from './app/protocol'
import { useBench, type ActiveExpect } from './app/useBench'
import { useCamera } from './app/useCamera'
import { Bench } from './screens/Bench'
import { Calibrate } from './screens/Calibrate'
import { Intro } from './screens/Intro'
import { ManualPage } from './screens/Manual'
import { CantHelp, ConfirmNewStudent, GoodLuck, Picker, Reconnecting, Shortcuts } from './screens/Screens'
import { ChatSheet, type DockState } from './ui/Chat'
import { Banner, BookButton, Reading, StatusChip, type ChipStatus, type NavState, type ProbeAsk, type ReadingTone } from './ui/kit'
import './theme.css'

type Screen = 'intro' | 'picker' | 'calibrate' | 'bench' | 'done'

const CANT_HELP_AFTER_MS = 90_000 // server down this long → "ask a TA" (C7)
const SHOW_CLEARED_MS = 4000 // keep a finished probe reading on screen this long

export default function App() {
  const mediaRef = useRef<HTMLVideoElement | null>(null)
  const calRef = useRef<Calibration | null>(null)
  const sendRef = useRef<(m: ClientMsg) => void>(() => {})

  // ALTA wants to look at the board: reply with the annotated frame (look_at_board, #20).
  const onRequestFrame = useCallback((id: string) => {
    const el = mediaRef.current
    if (!el) return
    try {
      sendRef.current({ type: 'frame', id, ...captureAnnotatedFrame(el, calRef.current) })
    } catch (e) {
      console.warn('[frame] not sent:', (e as Error).message)
    }
  }, [])
  const { bench, send, retryNow, resetLocal } = useBench({ onRequestFrame })
  const cam = useCamera()

  const [screen, setScreen] = useState<Screen>('intro')
  const [labId, setLabId] = useState<string | null>(null)
  const [uiStep, setUiStep] = useState(0) // 0 = setup, 1…n = manual steps
  const [confirmed, setConfirmed] = useState(0) // highest step ALTA has confirmed
  const [manual, setManual] = useState<{ focus?: string } | null>(null) // the open manual pop-up, at this section id
  const [chatOpen, setChatOpen] = useState(false)
  const [confirmNew, setConfirmNew] = useState(false)
  const [help, setHelp] = useState(false)
  const [draft, setDraft] = useState('')
  const [typing, setTyping] = useState(false)
  const [talking, setTalking] = useState(false)
  const [podBack, setPodBack] = useState(false)
  const [now, setNow] = useState(() => Date.now())
  const inputRef = useRef<HTMLInputElement>(null)

  // ---------- lab: whatever the server sent last (`lab`), once it's the one we picked ----------
  const lab: Lab | null = bench.lab && (!labId || bench.lab.id === labId) ? bench.lab : null
  const steps = useMemo(() => guideSteps(lab), [lab])
  const cards = useLabCards(bench.conn === 'open')
  const title = labTitle(lab?.title ?? cards.find((c) => c.id === labId)?.title ?? '')

  // ---------- calibration (per camera, saved in localStorage by the engine) ----------
  const deviceId = cam.source?.id ?? 'none'
  const [calVersion, setCalVersion] = useState(0) // bumps after saving, to re-read it
  const calibration = useMemo(() => loadCalibration(deviceId), [deviceId, calVersion])

  // latest values for the socket's frame handler
  useLayoutEffect(() => {
    sendRef.current = send
    calRef.current = calibration
  })

  // ---------- server steps ----------
  // `manual` moves the guide (ALTA's show_manual_step). Step 1 on connect doesn't skip the setup card.
  const lastStepAt = useRef(0)
  useEffect(() => {
    if (bench.stepAt === lastStepAt.current) return
    lastStepAt.current = bench.stepAt
    if (uiStep === 0 && bench.step <= 1) return
    if (bench.step > uiStep) setConfirmed((c) => Math.max(c, bench.step - 1)) // ALTA moved on, so the earlier steps are done
    setUiStep(bench.step)
  }, [bench.stepAt, bench.step, uiStep])

  // ---------- the probe reading ALTA asked for ----------
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(t)
  }, [])
  const active: ActiveExpect | null = useMemo(() => {
    const list = Object.values(bench.expects).filter((e): e is ActiveExpect => !!e && (!e.clearedAt || now - e.clearedAt < SHOW_CLEARED_MS))
    return list.sort((a, b) => b.since - a.since)[0] ?? null
  }, [bench.expects, now])
  const podDown = bench.health?.pod === 'down'
  const reading = useMemo(() => (active ? readingFor(active, bench.probes?.mv, podDown) : null), [active, bench.probes, podDown])
  // every probe ALTA is waiting on, for the probe readings row under the camera
  const asked = useMemo(() => {
    const out: Partial<Record<Probe, ProbeAsk>> = {}
    for (const e of Object.values(bench.expects)) if (e && !e.clearedAt) out[e.probe] = { where: whereLabel(e.at), expected_mv: e.expected_mv, tol_mv: e.tol_mv }
    return out
  }, [bench.expects])

  // ALTA confirms a step when the requested reading lands in range, or says so (a ✓ system line).
  useEffect(() => {
    if (uiStep >= 1 && reading?.tone === 'good' && active && !active.clearedAt) setConfirmed((c) => Math.max(c, uiStep))
  }, [reading?.tone, active, uiStep])
  const lastLine = bench.lines[bench.lines.length - 1]
  useEffect(() => {
    if (uiStep >= 1 && lastLine?.role === 'system' && lastLine.final && /✓\s*$/.test(lastLine.text)) setConfirmed((c) => Math.max(c, uiStep))
  }, [lastLine, uiStep])

  // ---------- overlay: ALTA's highlights + the strip each requested probe should go in ----------
  const overlay: OverlayItem[] = useMemo(() => {
    const items = [...bench.overlay]
    for (const e of Object.values(bench.expects)) {
      if (!e || e.clearedAt || !e.at) continue
      const at = stripOf(e.at)
      if (!items.some((i) => i.at === at)) items.push({ id: `expect-${e.probe}`, kind: 'strip', at, style: `probe-${e.probe}`, pulse: true })
    }
    return items
  }, [bench.overlay, bench.expects])

  // ---------- health ----------
  const serverDown = bench.conn !== 'open' && bench.downSince !== null
  const prevPod = useRef(bench.health?.pod)
  useEffect(() => {
    const was = prevPod.current
    prevPod.current = bench.health?.pod
    if (was === 'down' && bench.health?.pod === 'ok') {
      setPodBack(true)
      const t = window.setTimeout(() => setPodBack(false), 3000)
      return () => window.clearTimeout(t)
    }
  }, [bench.health?.pod])

  const part = (p: Part): ChipStatus => (bench.conn !== 'open' ? 'off' : bench.health?.[p] === 'down' ? 'problem' : bench.health?.[p] === 'off' ? 'off' : 'ok')
  const altaChip: ChipStatus = serverDown ? 'problem' : part('ai') === 'problem' || part('voice') === 'problem' ? 'problem' : part('ai') === 'off' && part('voice') === 'off' ? 'off' : 'ok'
  const chips = (
    <>
      <StatusChip label="Pod" status={part('pod')} title={bench.health?.fix.pod} />
      <StatusChip label="Camera" status={cam.status === 'ok' ? 'ok' : cam.status === 'missing' ? 'problem' : 'off'} title={cam.source?.label} />
      <StatusChip label="ALTA" status={altaChip} title={bench.health?.fix.ai ?? bench.health?.fix.voice} />
    </>
  )
  const banner =
    bannerFor(bench.health, podBack, retryNow) ??
    (cam.status === 'ok' && !calibration ? (
      <Banner icon="refresh" title="Board not calibrated" body="Click the 4 corner holes once so ALTA can point at holes on the camera." action="Calibrate" onAction={() => setScreen('calibrate')} />
    ) : null)

  // ---------- chat dock ----------
  const voiceDown = bench.health?.voice === 'down'
  const aiDown = bench.health?.ai === 'down'
  const dockState: DockState =
    talking || bench.state === 'listening'
      ? 'listening'
      : typing || draft
        ? 'typing'
        : aiDown || bench.state === 'error'
          ? 'offline'
          : bench.state === 'thinking' || bench.state === 'transcribing'
            ? 'thinking'
            : bench.state === 'speaking'
              ? 'speaking'
              : 'idle'

  // The caption is only ever a line from the server; with none yet, a muted how-to hint.
  let tag = 'ALTA'
  let tagTone: 'blue' | 'muted' | 'orange' = 'blue'
  let caption = ''
  let italic = false
  if (aiDown && bench.health?.fix.ai) {
    tag = 'NOTE'
    tagTone = 'orange'
    caption = bench.health.fix.ai
  } else if (lastLine) {
    caption = lastLine.text
    italic = !lastLine.final
    if (lastLine.role === 'student') [tag, tagTone] = ['You', 'muted']
    if (lastLine.role === 'system') [tag, tagTone] = ['NOTE', 'muted']
  }
  if (dockState === 'listening' && !(lastLine?.role === 'student' && !lastLine.final)) {
    ;[tag, tagTone, caption, italic] = ['You', 'muted', 'Listening…', true]
  }
  const hint = !caption
  if (hint) [tag, caption] = ['', 'Hold the mic (or Space) to talk to ALTA, or press / to type.']

  const talk = useCallback(
    (down: boolean) => {
      setTalking(down)
      send({ type: 'ptt', down })
    },
    [send],
  )
  const sendText = () => {
    const text = draft.trim()
    if (!text) return
    send({ type: 'text', text })
    setDraft('')
    inputRef.current?.blur()
  }
  const inputProps = {
    dock: dockState,
    draft,
    setDraft,
    onSend: sendText,
    inputRef,
    micDisabled: voiceDown || serverDown,
    micTitle: voiceDown ? 'ALTA’s voice is down. Press / to type' : undefined,
    onTalk: talk,
    onFocusChange: setTyping,
  }
  const dock = { ...inputProps, tag, tagTone, caption, italic, muted: hint, onPullUp: () => setChatOpen(true) }

  // ---------- flow ----------
  const startLab = (id: string) => {
    setLabId(id)
    send({ type: 'select_lab', lab_id: id })
    setUiStep(0)
    setConfirmed(0)
    setScreen('bench')
    setManual({}) // read the manual first (from the top); closing it shows the bench behind
  }
  const goStep = (n: number) => {
    setUiStep(n)
    if (n >= 1) send({ type: 'step', step: n })
  }
  const total = steps.length
  const cur = steps.find((s) => s.n === uiStep)
  const nav: NavState = uiStep === 0 ? 'setup' : confirmed >= uiStep ? (uiStep >= total ? 'last' : 'confirmed') : 'locked'
  const guide = {
    step: uiStep,
    total,
    title: uiStep === 0 ? 'Set up the probe pod' : (cur?.title ?? ''),
    text: uiStep === 0 ? setupText(lab?.manual_md ?? '') : (cur?.text ?? ''),
    nav,
    onBack: () => (uiStep === 0 ? setScreen('picker') : goStep(uiStep - 1)),
    onNext: () => (uiStep >= total ? setScreen('done') : goStep(uiStep + 1)),
  }
  const newStudent = () => {
    send({ type: 'reset' })
    resetLocal()
    setConfirmNew(false)
    setManual(null)
    setChatOpen(false)
    setDraft('')
    setUiStep(0)
    setConfirmed(0)
    setScreen('picker')
  }
  const openManual = (focus?: string) => lab?.manual_md && setManual({ focus: focus ?? (uiStep >= 1 ? `step-${uiStep}` : 'experimental-procedure') })

  // ---------- keyboard (#31): Space talk, / type, M manual, R recalibrate, N new student, ? help ----------
  const keys = useRef({ screen, manual, talking, talk, openManual })
  useLayoutEffect(() => {
    keys.current = { screen, manual, talking, talk, openManual }
  })
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      const k = keys.current
      const inField = e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement
      if (e.key === 'Escape') {
        setManual(null)
        setChatOpen(false)
        setConfirmNew(false)
        setHelp(false)
        return
      }
      if (inField || e.metaKey || e.ctrlKey || e.altKey || k.screen === 'intro') return
      const atBench = k.screen === 'bench' || k.screen === 'done'
      if (e.code === 'Space' && atBench && !k.manual) {
        e.preventDefault()
        if (!e.repeat && !k.talking) k.talk(true)
      } else if (e.key === '/' && atBench) {
        e.preventDefault()
        setManual(null)
        inputRef.current?.focus()
      } else if (e.key === '?') setHelp((h) => !h)
      else if ((e.key === 'm' || e.key === 'M') && atBench) {
        if (k.manual) setManual(null)
        else k.openManual()
      } else if ((e.key === 'r' || e.key === 'R') && atBench) setScreen('calibrate')
      else if ((e.key === 'n' || e.key === 'N') && k.screen !== 'picker') setConfirmNew(true)
    }
    const up = (e: KeyboardEvent) => {
      if (e.code === 'Space' && keys.current.talking) keys.current.talk(false)
    }
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
    }
  }, [])

  // ---------- render ----------
  const headerRight = (
    <>
      {chips}
      <BookButton onClick={() => openManual()} />
    </>
  )
  let page: ReactNode
  if (screen === 'intro') page = <Intro onDone={() => setScreen('picker')} />
  else if (serverDown && bench.downSince && now - bench.downSince > CANT_HELP_AFTER_MS) page = <CantHelp chips={chips} onRetry={retryNow} />
  else if (screen === 'calibrate')
    page = (
      <Calibrate
        title={title}
        chips={chips}
        cam={cam}
        mediaRef={mediaRef}
        initial={calibration}
        onBack={() => setScreen('bench')}
        onDone={(c) => {
          saveCalibration(c)
          setCalVersion((v) => v + 1)
          setScreen('bench')
        }}
      />
    )
  else if (screen === 'picker' || !lab) page = <Picker cards={cards} chips={chips} onStart={startLab} />
  else if (screen === 'done')
    page = (
      <GoodLuck
        title={title}
        labId={lab.id}
        headerRight={headerRight}
        dock={dock}
        onManual={() => openManual('measurements-and-observations')}
        onLabs={() => setScreen('picker')}
        onNewStudent={() => setConfirmNew(true)}
      />
    )
  else
    page = (
      <Bench
        lab={lab}
        headerRight={headerRight}
        cam={cam}
        mediaRef={mediaRef}
        calibration={calibration}
        overlay={overlay}
        banner={banner}
        reading={reading && <Reading {...reading} />}
        probes={{ mv: bench.probes?.mv, asked, paused: podDown }}
        guide={guide}
        chat={{ ...inputProps, lines: bench.lines }}
      />
    )

  return (
    <div className="app">
      {page}
      {manual && lab?.manual_md && <ManualPage title={title} md={lab.manual_md} focus={manual.focus} onClose={() => setManual(null)} />}
      {chatOpen && <ChatSheet lines={bench.lines} onClose={() => setChatOpen(false)} {...inputProps} />}
      {screen !== 'intro' && serverDown && !(bench.downSince && now - bench.downSince > CANT_HELP_AFTER_MS) && <Reconnecting onRetry={retryNow} />}
      {confirmNew && <ConfirmNewStudent onCancel={() => setConfirmNew(false)} onConfirm={newStudent} />}
      {help && <Shortcuts onClose={() => setHelp(false)} />}
    </div>
  )
}

function readingFor(e: ActiveExpect, mv: number[] | undefined, podDown: boolean): { probe: Probe; where: string; value: string; status: string; tone: ReadingTone } {
  const i = ['Y', 'B', 'G', 'W'].indexOf(e.probe)
  const v = mv?.[i]
  const where = `${PROBE_NAME[e.probe]} probe${e.at ? ` · ${whereLabel(e.at)}` : ''}`
  if (podDown) return { probe: e.probe, where, value: '—', status: 'Paused', tone: 'waiting' }
  if (v === undefined) return { probe: e.probe, where, value: '—', status: 'Waiting…', tone: 'waiting' }
  if (v < 0) return { probe: e.probe, where, value: '—', status: 'Unplugged', tone: 'waiting' }
  const value = `${(v / 1000).toFixed(2)} V`
  if (e.expected_mv === undefined) return { probe: e.probe, where, value, status: 'Reading', tone: 'waiting' }
  const tol = e.tol_mv ?? 250
  if (Math.abs(v - e.expected_mv) <= tol) return { probe: e.probe, where, value, status: 'Good', tone: 'good' }
  return { probe: e.probe, where, value, status: v > e.expected_mv ? 'Too high' : 'Too low', tone: 'bad' }
}

/** One-line fixes from `health` (#31). "Title. Body" lines split at the first full stop. */
function bannerFor(health: Health | null, podBack: boolean, retry: () => void): ReactNode {
  const split = (fix: string, fallbackTitle: string): [string, string] => {
    const i = fix.indexOf('. ')
    return i > 0 ? [fix.slice(0, i), fix.slice(i + 2).replace(/\.?$/, '.')] : [fallbackTitle, fix.replace(/\.?$/, '.')]
  }
  if (health?.pod === 'down') {
    const [t, b] = split(health.fix.pod ?? "Plug the pod's USB cable back in", 'Readings paused')
    return <Banner icon="unplug" title={t} body={b} action="Retry" onAction={retry} />
  }
  if (health?.ai === 'down') {
    const [t, b] = split(health.fix.ai ?? "ALTA can't reach its brain. Check internet / hotspot", 'ALTA is offline')
    return <Banner icon="wifi-off" title={t} body={b} action="Retry" onAction={retry} />
  }
  if (health?.voice === 'down') {
    const [t, b] = split(health.fix.voice ?? "ALTA's voice isn't responding. Check internet / hotspot", 'Voice is offline')
    return <Banner icon="wifi-off" title={t} body={b} />
  }
  if (podBack) return <Banner icon="check" title="Pod reconnected" body="Readings are live again." />
  return null
}
