// WebSocket message shapes from docs/CONTRACTS.md §5 (source of truth: issue #2).

import type { OverlayItem } from '../board'

export type Probe = 'Y' | 'B' | 'G' | 'W'
export const PROBES: Probe[] = ['Y', 'B', 'G', 'W']
export const PROBE_NAME: Record<Probe, string> = { Y: 'Yellow', B: 'Blue', G: 'Green', W: 'White' }

export type BenchState = 'idle' | 'listening' | 'transcribing' | 'thinking' | 'speaking' | 'error'
export type Part = 'pod' | 'ai' | 'voice'
export type PartStatus = 'ok' | 'down' | 'off'
export type Health = Record<Part, PartStatus> & { fix: Partial<Record<Part, string>> }

export type LabPart = { ref: string; kind: string; color?: string; value_ohm?: number; pins: Record<string, string> }
export type LabNet = { id: string; label: string; holes: string[]; expected_mv: number; tol_mv: number }
export type LabStep = { n: number; title: string; nets?: string[] }
export type Lab = {
  id: string
  title: string
  parts?: LabPart[]
  nets?: LabNet[]
  steps?: LabStep[]
  manual_md?: string
  schematic_url?: string | null
}

export type Expect = { probe: Probe; at?: string; expected_mv?: number; tol_mv?: number; label?: string; clear?: boolean }
export type Probes = { mv: number[]; lo: number[]; hi: number[]; vcc: number; btn: number; t: number }
export type Line = { role: 'student' | 'bench' | 'system'; text: string; final: boolean }

export type ServerMsg =
  | { type: 'lab'; lab: Lab }
  | ({ type: 'probes' } & Probes)
  | ({ type: 'expect' } & Expect)
  | { type: 'overlay'; mode: 'replace' | 'add'; items: OverlayItem[] }
  | { type: 'overlay_clear' }
  | { type: 'manual'; step: number }
  | { type: 'schematic'; nets: string[] }
  | ({ type: 'transcript' } & Line)
  | { type: 'state'; value: BenchState; detail?: string }
  | { type: 'request_frame'; id: string }
  | { type: 'error'; message: string }
  | ({ type: 'health' } & Health)

export type ClientMsg =
  | { type: 'hello'; client: 'student-screen' }
  | { type: 'select_lab'; lab_id: string }
  | { type: 'ptt'; down: boolean }
  | { type: 'text'; text: string }
  | { type: 'frame'; id: string; jpeg_b64: string; w: number; h: number }
  | { type: 'step'; step: number }
  | { type: 'reset' }
