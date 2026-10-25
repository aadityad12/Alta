// The 4:3 camera frame (#30): the live video, with layers on top that get the video's intrinsic size
// (for <BoardOverlay> and calibration). Shows "Camera missing" (C3) when there's no camera.

import { useEffect, useLayoutEffect, useRef, type MutableRefObject, type ReactNode } from 'react'
import { useMediaSize } from '../board'
import { FIT, type CameraStatus, type Source } from '../app/useCamera'
import cameraOff from '../assets/figma/camera-off.svg'
import { Button } from '../ui/kit'
import './screens.css'

type Props = {
  source: Source | null
  stream: MediaStream | null
  status: CameraStatus
  mediaRef: MutableRefObject<HTMLVideoElement | null>
  onRetry: () => void
  onSize?: (size: { w: number; h: number }) => void
  children?: (size: { w: number; h: number }) => ReactNode // layers that need the video's pixel size
  extra?: ReactNode // banner / reading, pinned inside the frame
}

/** 4:3, as wide as its column (screens.css sizes the column). */
export function CameraFrame({ source, stream, status, mediaRef, onRetry, onSize, children, extra }: Props) {
  const localRef = useRef<HTMLVideoElement | null>(null)
  const { w, h } = useMediaSize(localRef, `${source?.id}:${status}:${stream?.id}`)

  const onSizeRef = useRef(onSize)
  useLayoutEffect(() => {
    onSizeRef.current = onSize
  })
  useEffect(() => {
    if (w && h) onSizeRef.current?.({ w, h })
  }, [w, h])

  useEffect(() => {
    const el = localRef.current
    if (!el) return
    el.srcObject = stream
    if (stream) el.play().catch(() => {})
  }, [stream])

  const setRef = (el: HTMLVideoElement | null) => {
    localRef.current = el
    mediaRef.current = el
  }

  const missing = status === 'missing' || !source
  return (
    <div className={`camera${missing ? ' camera-missing' : ''}`}>
      {missing ? (
        <div className="camera-empty">
          <img src={cameraOff} width={48} height={48} alt="" />
          <h3 className="t-h2">Camera missing</h3>
          <p className="t-body-l c-60">Reconnect the camera, then press Try again.</p>
          <Button onClick={onRetry}>Try again</Button>
        </div>
      ) : (
        <>
          <video ref={setRef} className="camera-media" style={{ objectFit: FIT }} autoPlay muted playsInline />
          {w > 0 && h > 0 && children?.({ w, h })}
          {extra}
        </>
      )}
    </div>
  )
}
