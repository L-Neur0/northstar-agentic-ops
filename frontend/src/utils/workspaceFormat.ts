/**
 * The words and dates of the workspace screens (spec 23 §19.6, §19.8; AC-23.119, AC-23.127).
 * Why: the list, the summary cards and the step grid must say the same thing for the same status,
 * source or outcome, and the step grid must show the server's display text safely.
 * Rules: grid cell values arrive as display text made by the server (Q15), so `formatCell` only
 * maps an empty value to "—" and never parses, formats or renders Markdown or HTML; status words
 * match Home (part 1 §3.3). Must not: compute any number or decide any status.
 */
import { DOCUMENT_KIND_WORDS, type SessionStatus } from '../types/process-discovery'
import type { PillTone } from '../components/ui/Pill'
import type { ReviewFilters } from '../types/workspace'

export const NO_FILTERS: ReviewFilters = { status: null, cluster: null, q: '' }

export const EMPTY = '—'

export const STATUS_WORDS: Record<SessionStatus, string> = {
  active: 'In progress',
  finished: 'Mapped',
  no_candidate: 'Ended · nothing to map',
}

export const STATUS_TONES: Record<SessionStatus, PillTone> = { active: 'info', finished: 'success', no_candidate: 'neutral' }

export const statusWord = (status: SessionStatus | string): string => STATUS_WORDS[status as SessionStatus] ?? status

const SOURCE_WORDS: Record<string, string> = { expert: 'expert', document: 'from a document', specialist: 'specialist' }

export const sourceWord = (source: string | null): string => (source ? (SOURCE_WORDS[source] ?? source) : '')

export const outcomeWord = (outcome: string): string => (outcome === 'failed' ? 'could not be read' : 'read')

export const kindWord = (kind: string): string => DOCUMENT_KIND_WORDS[kind.toLowerCase()] ?? kind.toUpperCase()

/** A grid cell's display text, or "—" when empty (Q15: the server formats, the client does not). */
export function formatCell(value: string | null | undefined): string {
  return typeof value === 'string' && value.trim() ? value : EMPTY
}

/** Text or "—". */
export const orDash = (value: string | null | undefined): string => (value && value.trim() ? value : EMPTY)

const DATE = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
const DATE_TIME = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

/** "20 Nov 2026", or "" for a bad date. */
export function formatDate(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : DATE.format(d)
}

/** "20 Nov 2026, 14:05", or "" for a bad date. */
export function formatDateTime(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : DATE_TIME.format(d)
}
