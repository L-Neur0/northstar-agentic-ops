/**
 * Open / closed state of the panel sections and its automatic rules (spec 23 §3.8.7; AC-23.32).
 * Why: the panel follows the interview: on `steps` the five upper sections fold away and Steps
 * opens, on `review` every section with a gap opens again (no Roles and systems section since 2026-11-21).
 * A section the expert clicked is pinned and never changes by itself after that.
 * The Documents section (spec 23 §11.1) starts open and no phase rule ever closes it.
 * Rules: pure functions over one map `{[sectionId]: {collapsed, pinned}}` kept in page state;
 * gaps are read from the server's field views and flags, never computed from values.
 */
import { PROCESS_SECTIONS, type PanelSectionId, type Phase, type SessionOut } from '../../types/process-discovery'
import { sectionHasGaps, sectionViews } from '../../utils/processFieldScore'

export interface SectionState {
  collapsed: boolean
  pinned: boolean
}

export type SectionStateMap = Record<PanelSectionId, SectionState>

const ALL: PanelSectionId[] = [...PROCESS_SECTIONS, 'steps', 'documents']

export function defaultSections(): SectionStateMap {
  return Object.fromEntries(ALL.map((id) => [id, { collapsed: false, pinned: false }])) as SectionStateMap
}

/** A click toggles the section and pins it. */
export function toggleSection(map: SectionStateMap, id: PanelSectionId): SectionStateMap {
  return { ...map, [id]: { collapsed: !map[id].collapsed, pinned: true } }
}

function hasGap(id: PanelSectionId, session: SessionOut): boolean {
  if (id === 'documents') return false // open by default and never closed by the walk (spec 23 §11.1)
  const p = session.profile.process
  if (id === 'steps') {
    return !p.substeps_complete || session.fieldViews.some((v) => v.phase === 'steps' && v.status !== 'complete' && !v.key.endsWith('.handover'))
  }
  return sectionHasGaps(sectionViews(session.fieldViews, id))
}

/** The automatic open / close on entering a phase; pinned sections are left alone. */
export function applyPhase(map: SectionStateMap, phase: Phase, session: SessionOut): SectionStateMap {
  const next = { ...map }
  const set = (id: PanelSectionId, collapsed: boolean) => {
    if (!next[id].pinned) next[id] = { ...next[id], collapsed }
  }
  if (phase === 'steps') {
    PROCESS_SECTIONS.forEach((id) => set(id, true))
    set('steps', false)
  } else if (phase === 'review' || phase === 'confirm') {
    ALL.forEach((id) => {
      if (hasGap(id, session)) set(id, false)
    })
  }
  return next
}
