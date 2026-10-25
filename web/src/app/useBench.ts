// useBench: the live /ws socket (#30). Connects, reconnects with backoff, and reduces the
// server's messages (CONTRACTS §5) into one state object the screens read.

import { useCallback, useEffect, useLayoutEffect, useReducer, useRef } from 'react'
import type { OverlayItem } from '../board'
import type { BenchState, ClientMsg, Expect, Health, Lab, Line, Probe, Probes, ServerMsg } from './protocol'

export type Conn = 'connecting' | 'open' | 'closed'
export type ActiveExpect = Expect & { since: number; clearedAt?: number }

export type Bench = {
  conn: Conn
  downSince: number | null // when the socket last dropped (server down), null while open
  lab: Lab | null
  probes: Probes | null
  expects: Partial<Record<Probe, ActiveExpect>>
  overlay: OverlayItem[]
  step: number // manual step from the server (`manual`)
  stepAt: number // bumps on every `manual`, so the same step can be re-announced
  nets: string[]
  lines: Line[] // final lines, plus the live partial line at the end
  state: BenchState
  detail?: string
  health: Health | null
  error: string | null
}

const INITIAL: Bench = {
  conn: 'connecting',
  downSince: null,
  lab: null,
  probes: null,
  expects: {},
  overlay: [],
  step: 1,
  stepAt: 0,
  nets: [],
  lines: [],
  state: 'idle',
  health: null,
  error: null,
}

type Action = { kind: 'conn'; conn: Conn } | { kind: 'msg'; msg: ServerMsg } | { kind: 'local-reset' }

const MAX_LINES = 60

function reduce(s: Bench, a: Action): Bench {
  if (a.kind === 'conn') {
    // (re)connected: the server re-sends what's still live (lab, step, pending expects, health), so drop
    // highlights and probe requests from before; a restarted server must not leave old ones on screen
    if (a.conn === 'open') return { ...s, conn: 'open', downSince: null, overlay: [], expects: {} }
    return { ...s, conn: a.conn, downSince: s.downSince ?? (a.conn === 'closed' ? Date.now() : null) }
  }
  if (a.kind === 'local-reset') return { ...s, expects: {}, overlay: [], lines: [], nets: [], step: 1, stepAt: s.stepAt + 1 }
  const m = a.msg
  switch (m.type) {
    case 'lab':
      return s.lab?.id === m.lab.id ? { ...s, lab: m.lab } : { ...s, lab: m.lab, expects: {}, overlay: [], nets: [] }
    case 'probes':
      return { ...s, probes: { mv: m.mv, lo: m.lo, hi: m.hi, vcc: m.vcc, btn: m.btn, t: m.t } }
    case 'expect': {
      const { type: _t, ...e } = m
      void _t
      const prev = s.expects[e.probe]
      if (e.clear) return prev ? { ...s, expects: { ...s.expects, [e.probe]: { ...prev, clearedAt: Date.now() } } } : s
      return { ...s, expects: { ...s.expects, [e.probe]: { ...e, since: Date.now() } } }
    }
    case 'overlay':
      return { ...s, overlay: m.mode === 'add' ? [...s.overlay.filter((i) => !m.items.some((n) => n.id === i.id)), ...m.items] : m.items }
    case 'overlay_clear':
      return { ...s, overlay: [] }
    case 'manual':
      return { ...s, step: m.step, stepAt: s.stepAt + 1 }
    case 'schematic':
      return { ...s, nets: m.nets }
    case 'transcript': {
      const line: Line = { role: m.role, text: m.text, final: m.final }
      const last = s.lines[s.lines.length - 1]
      const base = last && !last.final && last.role === m.role ? s.lines.slice(0, -1) : s.lines
      return { ...s, lines: [...base, line].slice(-MAX_LINES) }
    }
    case 'state':
      return { ...s, state: m.value, detail: m.detail }
    case 'health': {
      const { type: _t, ...h } = m
      void _t
      return { ...s, health: h }
    }
    case 'error':
      return { ...s, error: m.message }
    default:
      return s
  }
}

type Handlers = { onRequestFrame?: (id: string) => void }

export function useBench(handlers: Handlers = {}) {
  const [bench, dispatch] = useReducer(reduce, INITIAL)
  const wsRef = useRef<WebSocket | null>(null)
  const retryRef = useRef<{ timer: number | undefined; delay: number; connect: () => void }>({ timer: undefined, delay: 500, connect: () => {} })
  const handlersRef = useRef(handlers)
  useLayoutEffect(() => {
    handlersRef.current = handlers
  })

  useEffect(() => {
    let stopped = false
    const r = retryRef.current

    const connect = () => {
      window.clearTimeout(r.timer)
      wsRef.current?.close()
      dispatch({ kind: 'conn', conn: 'connecting' })
      const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`)
      wsRef.current = ws
      ws.onopen = () => {
        r.delay = 500
        dispatch({ kind: 'conn', conn: 'open' })
        ws.send(JSON.stringify({ type: 'hello', client: 'student-screen' } satisfies ClientMsg))
      }
      ws.onmessage = (e) => {
        let msg: ServerMsg
        try {
          msg = JSON.parse(e.data)
        } catch {
          return
        }
        if (msg.type === 'request_frame') handlersRef.current.onRequestFrame?.(msg.id)
        else dispatch({ kind: 'msg', msg })
      }
      ws.onclose = () => {
        if (wsRef.current !== ws || stopped) return
        dispatch({ kind: 'conn', conn: 'closed' })
        r.timer = window.setTimeout(connect, r.delay)
        r.delay = Math.min(5000, r.delay * 2)
      }
    }
    r.connect = connect
    connect()
    return () => {
      stopped = true
      window.clearTimeout(r.timer)
      wsRef.current?.close()
    }
  }, [])

  const send = useCallback((msg: ClientMsg) => {
    const ws = wsRef.current
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg))
  }, [])

  /** Reconnect right away (the "Retry now" button) instead of waiting for the backoff. */
  const retryNow = useCallback(() => {
    retryRef.current.delay = 500
    retryRef.current.connect()
  }, [])

  /** Clear the local view of the session (new student), on top of the server's `reset`. */
  const resetLocal = useCallback(() => dispatch({ kind: 'local-reset' }), [])

  return { bench, send, retryNow, resetLocal }
}
