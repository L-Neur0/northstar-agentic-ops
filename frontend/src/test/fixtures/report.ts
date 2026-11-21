/**
 * Discovery report fixtures shared by the fake API and the report tests (spec 23 §11.15.8).
 * Why: the report page must be tested on what the server really sends, so `euReport` is the
 * recorded `GET /api/sessions/{id}/report` sample of the EU monthly cost review (342 h; written by
 * `backend/scripts/export_api_samples.py`), and the variants change only what they are named for.
 * Report v2 (spec 27; amended 2026-11-21 (report v2)): the sample holds the six v2 parts.
 * What: `euReport` (complete), `euReportStepsFailed` (a failed note on part 5),
 * `euReportSimplifiedMap` (simplified map with the server's caption), `thinReport` (minimum
 * fields, many "—"). Must not: invent fields the wire model does not have, or hold logic.
 */
import recorded from './api/report.json'
import type { DiscoveryReport, PartKey } from '../../types/report'

const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T

export const euReport: DiscoveryReport = clone(recorded) as unknown as DiscoveryReport

export const STEPS_FAILED_TEXT = 'The step-by-step assessment could not be generated this time. The rest of the report is complete.'

export function withFailedNote(report: DiscoveryReport, keys: PartKey[]): DiscoveryReport {
  const next = clone(report)
  for (const key of keys) next[key].note = { kind: 'failed', text: STEPS_FAILED_TEXT }
  return next
}

export const euReportStepsFailed: DiscoveryReport = withFailedNote(euReport, ['steps'])

export const SIMPLIFIED_CAPTION = 'The map is simplified: it shows the main steps only.'

export const euReportSimplifiedMap: DiscoveryReport = (() => {
  const next = clone(euReport)
  if (next.map.diagram) next.map.diagram.simplified = true
  next.map.caption = SIMPLIFIED_CAPTION
  next.map.note = { kind: 'simplified', text: SIMPLIFIED_CAPTION }
  return next
})()

export const thinReport: DiscoveryReport = (() => {
  const next = clone(euReport)
  next.summary = { ...next.summary, sentences: [] }
  next.map = { ...next.map, diagram: null, systems: [], columns: [] }
  next.steps = { ...next.steps, rows: [], catalogueNote: null, note: { kind: 'empty', text: 'No steps to assess.' } }
  next.feasibility = { ...next.feasibility, bullets: [], gaps: '' }
  next.measures = {
    ...next.measures,
    fields: next.measures.fields.map((f) => ({ ...f, value: 'Not measured yet', status: 'empty' })),
  }
  return next
})()
