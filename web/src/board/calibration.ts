// Calibration: 4 clicked holes → homography from board mm to video pixels.
// Saved in localStorage per camera (deviceId), so it survives a page reload.

import { calibrationHoles, ROWS, type Pt } from './geometry'
import { invert, solveHomography, type H } from './homography'

export type Calibration = {
  deviceId: string
  videoW: number // intrinsic video size the clicks were made in
  videoH: number
  lastRow: number // row clicked at the far end (63 unless the board's end was out of frame)
  clicks: Pt[] // video px of 1a, <lastRow>a, <lastRow>j, 1j
  H: H // board mm → video px
}

export function makeCalibration(deviceId: string, videoW: number, videoH: number, clicks: Pt[], lastRow = ROWS): Calibration {
  const src = calibrationHoles(lastRow).map((h) => h.pt)
  return { deviceId, videoW, videoH, lastRow, clicks, H: solveHomography(src, clicks) }
}

/** The same calibration for a different video resolution (same camera, same framing). */
export function rescale(cal: Calibration, videoW: number, videoH: number): Calibration {
  if (cal.videoW === videoW && cal.videoH === videoH) return cal
  const sx = videoW / cal.videoW
  const sy = videoH / cal.videoH
  return makeCalibration(cal.deviceId, videoW, videoH, cal.clicks.map((p) => ({ x: p.x * sx, y: p.y * sy })), cal.lastRow)
}

/** Video px → board mm. */
export function inverseH(cal: Calibration): H {
  return invert(cal.H)
}

const KEY = 'bench.calibration.'

export function saveCalibration(cal: Calibration): void {
  try {
    localStorage.setItem(KEY + cal.deviceId, JSON.stringify(cal))
  } catch {
    // private mode / quota: calibration just won't persist
  }
}

export function loadCalibration(deviceId: string): Calibration | null {
  try {
    const raw = localStorage.getItem(KEY + deviceId)
    if (!raw) return null
    const c = JSON.parse(raw) as Calibration
    return makeCalibration(c.deviceId, c.videoW, c.videoH, c.clicks, c.lastRow) // recompute H; never trust stored maths
  } catch {
    return null
  }
}

export function clearCalibration(deviceId: string): void {
  try {
    localStorage.removeItem(KEY + deviceId)
  } catch {
    // ignore
  }
}
