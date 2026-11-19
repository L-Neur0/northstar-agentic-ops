/**
 * Display formatters for the interview side: field values, phase labels, status text, relative
 * time (spec 23 §3.8.8, §3.3.2–3; AC-23.7, AC-23.30).
 * Why: the panel, Home and the dialogs must word values the same way; one module keeps them in
 * step. Values are read from `session.profile` by the field view key, so configured labels and
 * 1-based step cell keys (`process.substeps[1].roles`) work everywhere.
 * Rules: formatting only. Must not decide whether a value is an answer (the server's field view
 * status does), and a none row or `none_identified` owner reads "None".
 */
import {
  PHASE_LABELS,
  type ApprovalRow,
  type ExceptionRow,
  type NoneRow,
  type Phase,
  type Profile,
  type RoleRow,
  type SensitiveRow,
  type SessionSummary,
} from '../types/process-discovery'

const CELL_KEY = /^process\.substeps\[(\d+)\]\.(\w+)$/

function isNone(row: unknown): row is NoneRow {
  return typeof row === 'object' && row !== null && (row as { none?: unknown }).none === true
}

/** Reads the raw value at a field key; `undefined` when the path does not exist. */
export function getValue(profile: Profile, key: string): unknown {
  const cell = CELL_KEY.exec(key)
  if (cell) {
    const step = profile.process.substeps[Number(cell[1]) - 1]
    return step ? (step as unknown as Record<string, unknown>)[cell[2]] : undefined
  }
  let current: unknown = profile
  for (const part of key.split('.')) {
    if (typeof current !== 'object' || current === null) return undefined
    current = (current as Record<string, unknown>)[part]
  }
  return current
}

function joinRows<T>(rows: Array<NoneRow | T>, render: (row: T) => string): string {
  if (rows.length === 0) return ''
  if (rows.some(isNone)) return 'None'
  return rows.map((row) => render(row as T)).join(', ')
}

const withDetail = (main: string, detail: string) => (detail.trim() ? `${main} (${detail})` : main)

export function formatValue(profile: Profile, key: string): string {
  const value = getValue(profile, key)
  if (value === undefined || value === null) return ''
  const leaf = key.split('.').pop()?.replace(/^substeps\[\d+\]$/, '') ?? key

  switch (leaf) {
    case 'cluster': {
      const c = value as Profile['process']['cluster']
      return c.code ? `${c.name} (${c.code})` : ''
    }
    case 'volume': {
      const v = value as Profile['process']['volume']
      if (v.count !== null && v.period.trim()) return `${v.count} per ${v.period}`
      return v.raw
    }
    case 'process_owner': {
      const o = value as Profile['process']['process_owner']
      return o.role.trim() ? o.role : o.none_identified ? 'None' : ''
    }
    case 'baseline_metric': {
      const b = value as Profile['process']['baseline_metric']
      if (b.value.trim() && b.unit.trim()) return `${b.value} ${b.unit}${b.estimated ? ' (estimated)' : ''}`
      return b.qualitative
    }
    case 'target_metric': {
      const t = value as Profile['process']['target_metric']
      return t.value.trim() || t.unit.trim() ? `${t.value} ${t.unit}`.trim() : ''
    }
    case 'variation': {
      const v = value as Profile['process']['variation']
      const same = v.same.trim().toLowerCase()
      if (same === 'yes') return 'Yes'
      if (same === 'no') return v.differences ? `No: ${v.differences}` : 'No'
      if (same === 'partly') return v.differences ? `Partly: ${v.differences}` : 'Partly'
      return v.same
    }
    case 'sensitive_data':
      return joinRows(value as Array<NoneRow | SensitiveRow>, (r) => withDetail(r.item, r.detail))
    case 'roles':
      return joinRows(value as Array<NoneRow | RoleRow>, (r) => (r.contribution.trim() ? `${r.role} – ${r.contribution}` : r.role))
    case 'approvals':
      return joinRows(value as Array<NoneRow | ApprovalRow>, (r) => withDetail(r.approver_role, r.waiting_time))
    case 'exceptions':
      return joinRows(value as Array<NoneRow | ExceptionRow>, (r) =>
        r.loops_back_to ? `${r.description} → back to step ${r.loops_back_to}` : r.description,
      )
    case 'data': {
      const d = value as { inputs: string[]; outputs: string[] }
      if (d.inputs.length === 0 && d.outputs.length === 0) return ''
      return `in: ${d.inputs.join(', ') || '…'} · out: ${d.outputs.join(', ') || '…'}`
    }
    case 'effort': {
      const e = value as { duration: string; frequency: string }
      return [e.duration, e.frequency].filter((s) => s.trim()).join(' · ')
    }
  }
  if (Array.isArray(value)) return value.join(', ')
  if (typeof value === 'string' || typeof value === 'number') return String(value)
  return ''
}

export function phaseLabel(phase: Phase | string): string {
  return PHASE_LABELS[phase as Phase] ?? phase
}

export function completenessPct(score: number): number {
  return Math.round(score * 100)
}

/** Status column of Home (spec 23 §3.3.3). */
export function sessionStatusText(s: Pick<SessionSummary, 'status' | 'phase' | 'reportStatus'>): string {
  if (s.status === 'finished') return s.reportStatus === 'validated' ? 'Mapped · Validated by IT' : 'Mapped'
  if (s.status === 'no_candidate') return 'Ended · nothing to map'
  return `In progress · ${phaseLabel(s.phase)}`
}

/** Coarse relative time: "just now", "5 minutes ago", "2 hours ago", "yesterday", "3 days ago". */
export function formatRelativeTime(iso: string, now: number = Date.now()): string {
  const mins = Math.floor((now - new Date(iso).getTime()) / 60_000)
  if (Number.isNaN(mins)) return ''
  if (mins < 1) return 'just now'
  if (mins < 60) return mins === 1 ? '1 minute ago' : `${mins} minutes ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return hours === 1 ? '1 hour ago' : `${hours} hours ago`
  const days = Math.floor(hours / 24)
  return days === 1 ? 'yesterday' : `${days} days ago`
}
