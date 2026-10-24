// Shapes from docs/CONTRACTS.md §5 (OverlayItem) and §6 (lab parts) that the engine reads.

export type OverlayStyle = 'probe-Y' | 'probe-B' | 'probe-G' | 'probe-W' | 'attention' | 'good' | 'bad'

export type OverlayItem = {
  id: string
  kind: 'hole' | 'strip' | 'rail' | 'arrow' | 'label' | 'component'
  at?: string
  from?: string
  to?: string
  text?: string
  ref?: string
  style?: OverlayStyle
  pulse?: boolean
}

export type LabPart = { ref: string; kind: string; pins: Record<string, string>; color?: string }

/** Only the part of a lab the overlay needs (the full `lab` message has more). */
export type LabLike = { id?: string; parts?: LabPart[] }
