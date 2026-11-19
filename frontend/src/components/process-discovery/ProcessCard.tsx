/**
 * The five process sections of "Your process" (spec 23 §3.8.2–6; AC-23.28–23.31).
 * Why: the card: collapsible sections with a count, one row per field.
 * Sections now follow the field view `phase` (About you, The process, Boundaries, Measures,
 * Number of steps) and rows show the server's status, so configured labels show as is.
 * Rules: the count tallies `complete` views; the cluster row (P05) offers the picker only while
 * the session is active and shows the agent's suggestion. Must not grade values.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57).
 */
import { PROCESS_SECTIONS, SECTION_OF_PHASE, type ClusterRef, type FieldView, type Profile, type ProcessSectionId } from '../../types/process-discovery'
import { countComplete, sectionViews } from '../../utils/processFieldScore'
import { formatValue } from '../../utils/discoveryFormat'
import { FieldRow } from './FieldRow'
import { SectionToggle } from './SectionToggle'
import type { SectionStateMap } from './sectionState'

interface Props {
  profile: Profile
  fieldViews: FieldView[]
  sections: SectionStateMap
  onToggle: (id: ProcessSectionId) => void
  canPickCluster: boolean
  onPickCluster: () => void
  clusterProposal: ClusterRef | null
}

export function ProcessCard({ profile, fieldViews, sections, onToggle, canPickCluster, onPickCluster, clusterProposal }: Props) {
  return (
    <div className="flex flex-col gap-2.5">
      {PROCESS_SECTIONS.map((id) => {
        const views = sectionViews(fieldViews, id)
        const { complete, total } = countComplete(views)
        const collapsed = sections[id].collapsed
        const bodyId = `section-body-${id}`
        return (
          <section key={id} className="overflow-hidden rounded-lg border border-line bg-surface">
            <SectionToggle
              title={SECTION_OF_PHASE[id]}
              count={`${complete}/${total}`}
              collapsed={collapsed}
              controls={bodyId}
              onToggle={() => onToggle(id)}
            />
            <ul id={bodyId} hidden={collapsed} className="px-3 pb-2">
              {views.map((v) => (
                <FieldRow key={v.key} view={v} value={formatValue(profile, v.key)}>
                  {v.key === 'process.cluster' && (
                    <>
                      {clusterProposal && (
                        <p className="mt-1 text-xs text-muted">
                          Suggested: {clusterProposal.name} ({clusterProposal.code}). Answer in the chat, or pick another.
                        </p>
                      )}
                      {canPickCluster && (
                        <button
                          type="button"
                          onClick={onPickCluster}
                          className="mt-1 text-xs text-link underline underline-offset-2 hover:text-fg"
                        >
                          {v.status === 'complete' ? 'Change cluster' : 'Pick cluster'}
                        </button>
                      )}
                    </>
                  )}
                </FieldRow>
              ))}
            </ul>
          </section>
        )
      })}
    </div>
  )
}
