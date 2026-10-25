// The board camera (#30): the phone on the stand (or any camera). The choice is remembered.

import { useCallback, useEffect, useState } from 'react'
import type { Fit } from '../board'

export type Source = { id: string; label: string; deviceId?: string }
export type CameraStatus = 'starting' | 'ok' | 'missing'

const KEY = 'alta.camera'

/** The live camera fills the 4:3 frame (overlay and calibration use the same fit). */
export const FIT: Fit = 'cover'

export function useCamera() {
  const [sources, setSources] = useState<Source[]>([])
  const [listed, setListed] = useState(false) // cameras enumerated at least once
  const [chosen, setChosen] = useState<string | null>(() => localStorage.getItem(KEY))
  const [stream, setStream] = useState<MediaStream | null>(null)
  const [status, setStatus] = useState<CameraStatus>('starting')
  const [attempt, setAttempt] = useState(0)

  // List cameras (labels only show once permission is granted).
  const listCameras = useCallback(async () => {
    let list: Source[] = []
    try {
      const devs = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === 'videoinput')
      list = devs.map((d, i) => ({ id: `camera:${d.deviceId || i}`, label: d.label || `Camera ${i + 1}`, deviceId: d.deviceId || undefined }))
    } catch {
      // no mediaDevices (insecure context): no cameras
    }
    setSources((old) => (old.map((c) => c.id + c.label).join() === list.map((c) => c.id + c.label).join() ? old : list))
    setListed(true)
    return list
  }, [])

  useEffect(() => {
    listCameras()
    navigator.mediaDevices?.addEventListener?.('devicechange', listCameras)
    return () => navigator.mediaDevices?.removeEventListener?.('devicechange', listCameras)
  }, [listCameras])

  // The saved camera, else the first one.
  const source = sources.find((s) => s.id === chosen) ?? sources[0] ?? null
  const sourceId = source?.id ?? null

  useEffect(() => {
    if (!listed) return
    if (!sourceId) {
      setStream(null)
      setStatus('missing')
      return
    }
    let live: MediaStream | null = null
    let cancelled = false
    setStatus('starting')
    const video: MediaTrackConstraints = { width: { ideal: 1920 }, height: { ideal: 1440 } }
    if (source?.deviceId) video.deviceId = { exact: source.deviceId }
    navigator.mediaDevices
      .getUserMedia({ video })
      .then((s) => {
        if (cancelled) return s.getTracks().forEach((t) => t.stop())
        live = s
        setStream(s)
        setStatus('ok')
        s.getVideoTracks()[0]?.addEventListener('ended', () => setStatus('missing'))
        listCameras() // labels are readable now
      })
      .catch(() => {
        if (cancelled) return
        setStream(null)
        setStatus('missing')
      })
    return () => {
      cancelled = true
      live?.getTracks().forEach((t) => t.stop())
    }
    // keyed on ids, not the source object (it's rebuilt every render)
  }, [listed, sourceId, source?.deviceId, attempt, listCameras])

  const choose = useCallback((id: string) => {
    localStorage.setItem(KEY, id)
    setChosen(id)
  }, [])

  const retry = useCallback(() => {
    listCameras()
    setAttempt((a) => a + 1)
  }, [listCameras])

  return { source, sources, stream, status, choose, retry }
}
