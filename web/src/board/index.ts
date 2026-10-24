// Overlay engine (#11) public API. See README.md in this folder.

export { BoardOverlay, GhostGrid } from './BoardOverlay'
export { useMediaSize, type Fit } from './media'
export { CalibrationLayer } from './CalibrationLayer'
export { captureAnnotatedFrame, type AnnotatedFrame } from './annotate'
export { loadCalibration, saveCalibration, clearCalibration, makeCalibration, inverseH, type Calibration } from './calibration'
export { parseLoc, tryParseLoc, nearestHole, type Loc } from './geometry'
export { STYLE_COLOR } from './styles'
export type { OverlayItem, OverlayStyle, LabLike, LabPart } from './types'
