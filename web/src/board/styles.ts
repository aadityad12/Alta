// Overlay colours. Placeholders until the #26 visual-language spec lands; change them here only.

import type { OverlayStyle } from './types'

export const STYLE_COLOR: Record<OverlayStyle, string> = {
  'probe-Y': '#facc15',
  'probe-B': '#3b82f6',
  'probe-G': '#22c55e',
  'probe-W': '#f8fafc',
  attention: '#f97316',
  good: '#22c55e',
  bad: '#ef4444',
}

/** Text colour that reads on top of each style colour (for label pills). */
export const STYLE_INK: Record<OverlayStyle, string> = {
  'probe-Y': '#1c1917',
  'probe-B': '#ffffff',
  'probe-G': '#052e16',
  'probe-W': '#0f172a',
  attention: '#1c1917',
  good: '#052e16',
  bad: '#ffffff',
}
