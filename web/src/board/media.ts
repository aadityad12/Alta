// Matching the overlay to the media element: object-fit and intrinsic size.

import { useEffect, useState, type RefObject } from 'react'

export type Fit = 'contain' | 'cover'

/** SVG preserveAspectRatio that reproduces each CSS object-fit (with the default centred object-position). */
export const ASPECT: Record<Fit, string> = { contain: 'xMidYMid meet', cover: 'xMidYMid slice' }

/** Intrinsic pixel size of a <video> or <img>, updated when the stream or image changes. */
export function useMediaSize(ref: RefObject<HTMLVideoElement | HTMLImageElement | null>, dep?: unknown): { w: number; h: number } {
  const [size, setSize] = useState({ w: 0, h: 0 })
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const read = () => {
      const w = el instanceof HTMLVideoElement ? el.videoWidth : el.naturalWidth
      const h = el instanceof HTMLVideoElement ? el.videoHeight : el.naturalHeight
      setSize((s) => (s.w === w && s.h === h ? s : { w, h }))
    }
    read()
    const events = ['loadedmetadata', 'resize', 'load']
    events.forEach((e) => el.addEventListener(e, read))
    return () => events.forEach((e) => el.removeEventListener(e, read))
  }, [ref, dep])
  return size
}
