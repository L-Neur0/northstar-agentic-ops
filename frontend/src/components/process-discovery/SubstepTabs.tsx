/**
 * The Steps section body: one tab per step and the **No further steps** button (spec 23
 * §3.8.9–10; AC-23.33, AC-23.50, AC-23.51).
 * Why: the sub-step tabs: `k · <name> (f/12)` tabs (`Step k (f/12)` while unnamed; the name cut with
 * an ellipsis, full in `title` and `aria-label`; amended 2026-11-21, §3.6 rule 11, AC-23.150) that scroll horizontally and
 * keep the active one in view, a panel with the thirteen cells of the chosen step in registry
 * order (S13 "Rules or judgement" after S12), S12 marked "(not scored)". Counts come from the
 * 1-based cell field views (`process.substeps[k].<leaf>`); S01–S11 and S13 are scored (short step
 * walk, amended 2026-11-20). S14 *Decision criteria* follows S13 only when the server sends its view
 * (a judgement or mix step), marked "(not scored)" and never counted (amended 2026-11-21, §3.6 rule 12,
 * AC-23.151). An agent proposal (source `agent`) gets the same ✓ / ✎ as a document one.
 * Part 2 (spec 23 §11.7, §11.8; AC-23.77, AC-23.78): proposed cells carry ✓ / ✎, a step with two
 * or more proposed cells offers "Confirm all <n> proposals in step k" (keys in field view order),
 * and a tab says "· proposed" in text while its step has a proposal.
 * Rules: the button is enabled only with at least one row, an open walk (`substeps_complete`
 * false), an active session and no confirm in flight; the server trims P16 when it is pressed.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57).
 */
import { Tabs } from '../ui/Tabs'
import { Button } from '../ui/Button'
import { FieldRow } from './FieldRow'
import type { ProposalControls } from './ProposalActions'
import { formatValue } from '../../utils/discoveryFormat'
import { parseCellKey, stepScore, viewsForStep } from '../../utils/substepProgress'
import { UNSCORED_STEP_LEAVES, type FieldView, type Profile } from '../../types/process-discovery'

interface Props {
  profile: Profile
  fieldViews: FieldView[]
  /** 0-based index of the shown step. */
  activeIndex: number
  onSelect: (index: number) => void
  sessionActive: boolean
  confirming: boolean
  onNoFurtherSteps: () => void
  proposals?: ProposalControls
  /** A document write is in flight: "No further steps" waits (spec 23 §11.4.3). */
  writing?: boolean
}

export function SubstepTabs({ profile, fieldViews, activeIndex, onSelect, sessionActive, confirming, onNoFurtherSteps, proposals, writing = false }: Props) {
  const rows = profile.process.substeps
  const canEnd = rows.length > 0 && !profile.process.substeps_complete && sessionActive && !confirming && !writing
  const index = Math.min(Math.max(activeIndex, 0), Math.max(rows.length - 1, 0))
  const stepViews = viewsForStep(fieldViews, index + 1)
  const proposedKeys = stepViews.filter((v) => v.status === 'proposed').map((v) => v.key)

  return (
    <div className="px-3 pb-3">
      {rows.length === 0 ? (
        <p className="py-2 text-sm italic text-subtle">The steps appear here once you start describing them.</p>
      ) : (
        <>
          <Tabs
            label="Steps"
            idPrefix="steps"
            selected={index}
            onSelect={onSelect}
            items={rows.map((row, i) => {
              const views = viewsForStep(fieldViews, i + 1)
              const score = stepScore(views)
              const proposed = views.some((v) => v.status === 'proposed') ? ' · proposed' : ''
              const name = row.name.trim()
              const count = `(${score.filled}/${score.total})`
              const answered = `${score.filled} of ${score.total} answered${proposed ? ', proposed' : ''}`
              if (!name) {
                return { id: `step-${i + 1}`, label: `Step ${i + 1} ${count}${proposed}`, ariaLabel: `Step ${i + 1}, ${answered}` }
              }
              const label = (
                <>
                  <span className="inline-block max-w-[12rem] truncate align-bottom">{`${i + 1} · ${name}`}</span> {count}
                  {proposed}
                </>
              )
              return { id: `step-${i + 1}`, label, title: name, ariaLabel: `Step ${i + 1}: ${name}, ${answered}` }
            })}
          />
          <div role="tabpanel" id="steps-panel" aria-labelledby={`steps-tab-${index}`} className="pt-2">
            <p className="mb-1 text-sm font-medium text-fg">
              Step {index + 1}
              {rows[index]?.name ? ` · ${rows[index].name}` : ''}
            </p>
            {proposals?.canAct && proposedKeys.length >= 2 && (
              <Button
                size="sm"
                className="mb-1"
                disabled={proposals.disabled}
                loading={proposals.pending?.kind === 'confirm' && proposals.pending.keys.length > 1 && proposals.pending.keys.every((k) => proposedKeys.includes(k))}
                onClick={() => proposals.onConfirm(proposedKeys)}
              >
                Confirm all {proposedKeys.length} proposals in step {index + 1}
              </Button>
            )}
            <ul>
              {stepViews.map((v) => (
                <FieldRow
                  key={v.key}
                  view={v}
                  value={formatValue(profile, v.key)}
                  notScored={UNSCORED_STEP_LEAVES.includes(parseCellKey(v.key)?.leaf ?? '')}
                  proposals={proposals}
                />
              ))}
            </ul>
          </div>
        </>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line pt-2">
        <Button size="sm" onClick={onNoFurtherSteps} disabled={!canEnd} loading={confirming && rows.length > 0 && !profile.process.substeps_complete}>
          No further steps
        </Button>
        {profile.process.substeps_complete ? (
          <span className="text-xs text-success">✓ The list of steps is closed.</span>
        ) : (
          <span className="text-xs text-subtle">Use this if the process has fewer steps than you said.</span>
        )}
      </div>
    </div>
  )
}
