/**
 * Section grouping and counts for the "Your process" panel (spec 23 §3.8.2; AC-23.28, AC-23.31).
 * Why: each `ProcessCard` section header shows `complete/total`; the client never computes fill rules
 * in the browser, here the count tallies the field views the server already graded.
 * Rules: count views with status `complete`, nothing else (proposed, partial, deferred do not
 * count). Must not: grade a value or read the profile.
 */
import type { FieldView, ProcessSectionId } from '../types/process-discovery'

const isCell = (v: FieldView) => v.key.startsWith('process.substeps[')

/** Process field views (not step cells) whose phase is the section. */
export function sectionViews(views: FieldView[], section: ProcessSectionId): FieldView[] {
  return views.filter((v) => !isCell(v) && v.phase === section)
}

export function countComplete(views: FieldView[]): { complete: number; total: number } {
  return { complete: views.filter((v) => v.status === 'complete').length, total: views.length }
}

export function sectionHasGaps(views: FieldView[]): boolean {
  return views.some((v) => v.status !== 'complete')
}
