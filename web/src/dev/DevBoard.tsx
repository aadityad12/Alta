// /dev/board: try the overlay engine (#11) on the #34 sample photos/video or a live camera.
// Calibrate, push highlights, hover to read hole names, capture the frame Claude would see.
// "Live" connects to the server's /ws and acts like the student screen for overlays + look_at_board.

import { useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent } from 'react'
import { parse as parseYaml } from 'yaml'
import {
  BoardOverlay,
  CalibrationLayer,
  captureAnnotatedFrame,
  clearCalibration,
  inverseH,
  loadCalibration,
  makeCalibration,
  nearestHole,
  saveCalibration,
  STYLE_COLOR,
  useMediaSize,
  type AnnotatedFrame,
  type Calibration,
  type Fit,
  type LabLike,
  type OverlayItem,
  type OverlayStyle,
} from '../board'
import { apply } from '../board/homography'
import { rescale } from '../board/calibration'

const SAMPLES = import.meta.glob(['../../../docs/samples/*.{jpg,mp4}', '!../../../docs/samples/setup-stand*'], { query: '?url', import: 'default', eager: true }) as Record<string, string>
const LAB_YAML = import.meta.glob('../../../labs/*/lab.yaml', { query: '?raw', import: 'default', eager: true }) as Record<string, string>

// Corner holes measured in board-empty-01.jpg, so the page shows something before anyone calibrates.
const PRESET: Record<string, { w: number; h: number; clicks: { x: number; y: number }[] }> = {
  'sample:board-empty-01.jpg': { w: 1600, h: 900, clicks: [{ x: 399.6, y: 355.1 }, { x: 1378.9, y: 342.4 }, { x: 1380.9, y: 165.4 }, { x: 393.1, y: 181.6 }] },
}

type Source = { id: string; label: string; kind: 'image' | 'video' | 'camera'; url?: string; deviceId?: string }

const STYLES: OverlayStyle[] = ['probe-Y', 'probe-B', 'probe-G', 'probe-W', 'attention', 'good', 'bad']
const KINDS: OverlayItem['kind'][] = ['strip', 'hole', 'rail', 'component', 'label', 'arrow']

const sampleSources: Source[] = Object.entries(SAMPLES).map(([p, url]) => {
    const name = p.split('/').pop()!
    return { id: `sample:${name}`, label: name, kind: name.endsWith('.mp4') ? 'video' : 'image', url }
  })

const labs: LabLike[] = Object.values(LAB_YAML).map((raw) => parseYaml(raw) as LabLike)

export default function DevBoard() {
  const [cameras, setCameras] = useState<Source[]>([])
  const sources = [...sampleSources, ...cameras]
  const [sourceId, setSourceId] = useState(sampleSources[0]?.id ?? '')
  const source = sources.find((s) => s.id === sourceId) ?? sources[0]
  const [fit, setFit] = useState<Fit>('contain')
  const [ghost, setGhost] = useState(true)
  const [calibrating, setCalibrating] = useState(false)
  const [labId, setLabId] = useState(labs[0]?.id ?? '')
  const [serverLab, setServerLab] = useState<LabLike | null>(null)
  const [live, setLive] = useState(false)
  const lab = (live && serverLab) || labs.find((l) => l.id === labId) || null
  const [items, setItems] = useState<OverlayItem[]>([{ id: 'demo', kind: 'strip', at: '10:a-e', style: 'probe-Y', pulse: true }])
  const [frame, setFrame] = useState<AnnotatedFrame | null>(null)
  const [hover, setHover] = useState('')
  const [log, setLog] = useState<string[]>([])
  const say = (m: string) => setLog((l) => [`${new Date().toLocaleTimeString()} ${m}`, ...l].slice(0, 30))

  const mediaRef = useRef<HTMLVideoElement | HTMLImageElement | null>(null)
  const { w, h } = useMediaSize(mediaRef, source?.id)

  // Calibration for this source: what was set this session, else the saved one, else the preset for sample 01.
  const sid = source?.id ?? ''
  const [calSet, setCalSet] = useState<Record<string, Calibration | null>>({})
  const stored = useMemo(() => {
    const p = PRESET[sid]
    return loadCalibration(sid) ?? (p ? makeCalibration(sid, p.w, p.h, p.clicks) : null)
  }, [sid])
  const cal = sid in calSet ? calSet[sid] : stored
  const setCal = (c: Calibration | null) => setCalSet((m) => ({ ...m, [sid]: c }))

  // Live camera stream.
  const cameraId = source?.kind === 'camera' ? source.deviceId : undefined
  useEffect(() => {
    if (!cameraId) return
    let stream: MediaStream | null = null
    navigator.mediaDevices
      .getUserMedia({ video: { deviceId: { exact: cameraId }, width: { ideal: 1920 }, height: { ideal: 1080 } } })
      .then((s) => {
        stream = s
        if (mediaRef.current instanceof HTMLVideoElement) mediaRef.current.srcObject = s
      })
      .catch((e) => say(`camera: ${e.message}`))
    return () => stream?.getTracks().forEach((t) => t.stop())
  }, [cameraId])

  const findCameras = async () => {
    try {
      const s = await navigator.mediaDevices.getUserMedia({ video: true }) // permission, so labels show
      s.getTracks().forEach((t) => t.stop())
      const devs = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === 'videoinput')
      setCameras(devs.map((d, i) => ({ id: d.deviceId, label: d.label || `camera ${i + 1}`, kind: 'camera', deviceId: d.deviceId })))
      say(`found ${devs.length} camera(s)`)
    } catch (e) {
      say(`camera: ${(e as Error).message}`)
    }
  }

  const capture = (): AnnotatedFrame | null => {
    if (!mediaRef.current) return null
    try {
      const f = captureAnnotatedFrame(mediaRef.current, cal)
      setFrame(f)
      return f
    } catch (e) {
      say(`capture: ${(e as Error).message}`)
      return null
    }
  }

  // Live mode: act as the student screen for overlay / lab / expect / request_frame.
  const captureRef = useRef(capture)
  useEffect(() => {
    captureRef.current = capture
  })
  useEffect(() => {
    if (!live) return
    const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`)
    ws.onopen = () => {
      ws.send(JSON.stringify({ type: 'hello', client: 'student-screen' }))
      say('live: connected')
    }
    ws.onclose = () => say('live: disconnected')
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data)
      if (m.type === 'lab') {
        setServerLab(m.lab)
        say(`live: lab ${m.lab.id}`)
      } else if (m.type === 'overlay') {
        setItems((cur) => (m.mode === 'add' ? [...cur, ...m.items] : m.items))
        say(`live: overlay ${m.mode} ${JSON.stringify(m.items)}`)
      } else if (m.type === 'overlay_clear') {
        setItems([])
        say('live: overlay_clear')
      } else if (m.type === 'expect') {
        const id = `expect-${m.probe}`
        setItems((cur) => [...cur.filter((i) => i.id !== id), ...(m.clear || !m.at ? [] : [{ id, kind: 'strip' as const, at: m.at, style: `probe-${m.probe}` as OverlayStyle, pulse: true }])])
        say(`live: expect ${m.probe} ${m.at ?? 'clear'}`)
      } else if (m.type === 'request_frame') {
        const f = captureRef.current()
        if (f) ws.send(JSON.stringify({ type: 'frame', id: m.id, ...f }))
        say(`live: request_frame ${m.id} → ${f ? `${f.w}×${f.h}, ${Math.round((f.jpeg_b64.length * 0.75) / 1024)} KB` : 'failed'}`)
      }
    }
    return () => ws.close()
  }, [live])

  const onHover = (e: PointerEvent<HTMLDivElement>) => {
    const el = mediaRef.current
    if (!cal || !el || !w) return setHover('')
    const r = el.getBoundingClientRect()
    const k = fit === 'contain' ? Math.min(r.width / w, r.height / h) : Math.max(r.width / w, r.height / h)
    const vx = (e.clientX - r.left - (r.width - w * k) / 2) / k
    const vy = (e.clientY - r.top - (r.height - h * k) / 2) / k
    const b = apply(inverseH(rescale(cal, w, h)), vx, vy)
    const n = nearestHole(b)
    setHover(n.dist < 2.54 ? `${n.name}  (${n.dist.toFixed(1)} mm from centre)` : `off the holes · video px ${vx.toFixed(0)}, ${vy.toFixed(0)}`)
  }

  const mediaStyle: CSSProperties = { position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: fit, background: '#000' }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 340px', gap: 16, padding: 16, font: '14px system-ui, sans-serif', color: '#e2e8f0', background: '#0f172a', minHeight: '100vh', boxSizing: 'border-box' }}>
      <div>
        <div
          style={{ position: 'relative', width: '100%', height: '70vh', resize: 'both', overflow: 'hidden', border: '1px solid #334155', borderRadius: 8 }}
          onPointerMove={onHover}
          onPointerLeave={() => setHover('')}
        >
          {source?.kind === 'image' ? (
            <img key={source.id} ref={(el) => void (mediaRef.current = el)} src={source.url} style={mediaStyle} alt="" />
          ) : (
            <video key={source?.id} ref={(el) => void (mediaRef.current = el)} src={source?.url} style={mediaStyle} autoPlay loop muted playsInline />
          )}
          {!calibrating && <BoardOverlay items={items} calibration={cal} lab={lab} videoW={w} videoH={h} fit={fit} ghost={ghost} />}
          {calibrating && w > 0 && (
            <CalibrationLayer
              deviceId={source.id}
              videoW={w}
              videoH={h}
              fit={fit}
              initial={cal}
              onDone={(c) => {
                saveCalibration(c)
                setCal(c)
                setCalibrating(false)
                say(`calibrated ${source.id} (far row ${c.lastRow})`)
              }}
              onCancel={() => setCalibrating(false)}
            />
          )}
        </div>
        <p style={{ margin: '6px 0', minHeight: 20, fontFamily: 'ui-monospace, monospace' }}>
          {hover || (cal ? 'hover the board to read hole names · drag the corner to resize' : 'not calibrated')} · video {w}×{h}
        </p>
        {frame && (
          <div>
            <h3 style={{ margin: '12px 0 6px' }}>
              What Claude sees: {frame.w}×{frame.h}, {Math.round((frame.jpeg_b64.length * 0.75) / 1024)} KB{' '}
              <a href={`data:image/jpeg;base64,${frame.jpeg_b64}`} download="annotated-frame.jpg" style={{ color: '#7dd3fc' }}>
                download
              </a>
            </h3>
            <img src={`data:image/jpeg;base64,${frame.jpeg_b64}`} style={{ maxWidth: '100%', borderRadius: 8 }} alt="annotated frame" />
          </div>
        )}
      </div>

      <aside style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <h2 style={{ margin: 0 }}>Overlay engine · /dev/board</h2>
        <Field label="Source">
          <select value={source?.id} onChange={(e) => setSourceId(e.target.value)}>
            {sources.map((s) => (
              <option key={s.id} value={s.id}>
                {s.kind === 'camera' ? '📷 ' : ''}
                {s.label}
              </option>
            ))}
          </select>
          <button onClick={findCameras}>Cameras…</button>
        </Field>
        <Field label="Fit">
          <select value={fit} onChange={(e) => setFit(e.target.value as Fit)}>
            <option value="contain">contain</option>
            <option value="cover">cover</option>
          </select>
          <label>
            <input type="checkbox" checked={ghost} onChange={(e) => setGhost(e.target.checked)} /> ghost grid
          </label>
        </Field>
        <Field label="Calibration">
          <button onClick={() => setCalibrating(true)} disabled={!w}>
            {cal ? 'Recalibrate' : 'Calibrate'}
          </button>
          <button
            onClick={() => {
              clearCalibration(source.id)
              setCal(null)
            }}
            disabled={!cal}
          >
            Clear
          </button>
        </Field>
        <Field label="Lab">
          <select value={lab?.id} onChange={(e) => setLabId(e.target.value)} disabled={!!serverLab}>
            {labs.map((l) => (
              <option key={l.id} value={l.id}>
                {l.id}
              </option>
            ))}
          </select>
          <label title="Connect to the server's /ws: apply its overlays and answer request_frame">
            <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} /> live
          </label>
        </Field>

        <ItemForm onAdd={(i) => setItems((cur) => [...cur.filter((c) => c.id !== i.id), i])} />

        <Field label="Presets">
          <button onClick={() => setItems((lab?.parts ?? []).map((p, i) => ({ id: `p${i}`, kind: 'component', ref: p.ref, style: STYLES[i % 4] })))}>All parts</button>
          <button
            onClick={() =>
              setItems([
                { id: 'ask', kind: 'strip', at: '10:a-e', style: 'probe-Y', pulse: true },
                { id: 'ask-l', kind: 'label', at: '10e', text: 'Yellow probe here', style: 'probe-Y' },
              ])
            }
          >
            Ask for probe
          </button>
          <button
            onClick={() =>
              setItems([
                { id: 'r', kind: 'rail', at: 'rail:a+', style: 'bad' },
                { id: 'r2', kind: 'rail', at: 'rail:a-', style: 'good' },
                { id: 'ar', kind: 'arrow', from: '6c', to: '10c', style: 'attention' },
              ])
            }
          >
            Rails + arrow
          </button>
          <button onClick={() => setItems([])}>Clear</button>
        </Field>
        <button onClick={capture} disabled={!w} style={{ padding: 8 }}>
          📸 Capture annotated frame
        </button>
        <details>
          <summary>Items ({items.length})</summary>
          <pre style={{ fontSize: 11, whiteSpace: 'pre-wrap' }}>{JSON.stringify(items, null, 1)}</pre>
        </details>
        <div style={{ fontFamily: 'ui-monospace, monospace', fontSize: 11, opacity: 0.8 }}>
          {log.map((l, i) => (
            <div key={i}>{l}</div>
          ))}
        </div>
      </aside>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
      <span style={{ width: 80, opacity: 0.7 }}>{label}</span>
      {children}
    </div>
  )
}

function ItemForm({ onAdd }: { onAdd: (i: OverlayItem) => void }) {
  const [kind, setKind] = useState<OverlayItem['kind']>('strip')
  const [a, setA] = useState('10:a-e')
  const [b, setB] = useState('')
  const [style, setStyle] = useState<OverlayStyle>('attention')
  const [pulse, setPulse] = useState(false)
  const n = useRef(0)
  const build = (): OverlayItem => {
    const id = `u${++n.current}`
    if (kind === 'component') return { id, kind, ref: a, style, pulse }
    if (kind === 'arrow') return { id, kind, from: a, to: b, style, pulse }
    if (kind === 'label') return { id, kind, at: a, text: b, style, pulse }
    return { id, kind, at: a, style, pulse }
  }
  const second = kind === 'arrow' ? 'to' : kind === 'label' ? 'text' : null
  return (
    <fieldset style={{ border: '1px solid #334155', borderRadius: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
      <legend>Add item</legend>
      <Field label="kind">
        <select value={kind} onChange={(e) => setKind(e.target.value as OverlayItem['kind'])}>
          {KINDS.map((k) => (
            <option key={k}>{k}</option>
          ))}
        </select>
      </Field>
      <Field label={kind === 'component' ? 'ref' : kind === 'arrow' ? 'from' : 'at'}>
        <input value={a} onChange={(e) => setA(e.target.value)} placeholder={kind === 'component' ? 'D1' : '10:a-e'} />
      </Field>
      {second && (
        <Field label={second}>
          <input value={b} onChange={(e) => setB(e.target.value)} />
        </Field>
      )}
      <Field label="style">
        <select value={style} onChange={(e) => setStyle(e.target.value as OverlayStyle)} style={{ color: STYLE_COLOR[style] }}>
          {STYLES.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
        <label>
          <input type="checkbox" checked={pulse} onChange={(e) => setPulse(e.target.checked)} /> pulse
        </label>
      </Field>
      <button onClick={() => onAdd(build())}>Add</button>
    </fieldset>
  )
}
