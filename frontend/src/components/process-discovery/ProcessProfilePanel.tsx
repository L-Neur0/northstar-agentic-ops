/**
 * The "Your process" side panel (spec 23 §3.8; AC-23.38, AC-23.39).
 * Why: the profile rail: the five process sections, the Steps section, the
 * Roles and systems section, then the *Finish* block (which takes the place of a "Generate
 * Prompt" and analysis buttons). All state is lifted to the page.
 * Rules: the *Finish* button follows `finish.ready` and the session status only; `looksLikeTask`
 * is an advisory note that never disables it; a blocked button shows its reason sentence, linked
 * by `aria-describedby`, and an unknown code is shown as is. Must not compute completeness.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57).
 */
import { Link } from 'react-router-dom'
import { FileCheck2, Info } from 'lucide-react'
import { Button } from '../ui/Button'
import { ProcessCard } from './ProcessCard'
import { SubstepTabs } from './SubstepTabs'
import { DerivedReviewPanel } from './DerivedReviewPanel'
import { SectionToggle } from './SectionToggle'
import type { SectionStateMap } from './sectionState'
import type { Pending } from '../../hooks/discoveryReducer'
import { completenessPct } from '../../utils/discoveryFormat'
import { settledStepCount } from '../../utils/substepProgress'
import {
  FINISH_BLOCKED_MESSAGES,
  type ConfirmTarget,
  type FinishBlock,
  type PanelSectionId,
  type SessionOut,
} from '../../types/process-discovery'

interface Props {
  session: SessionOut
  sections: SectionStateMap
  onToggleSection: (id: PanelSectionId) => void
  activeStep: number
  onSelectStep: (index: number) => void
  pending: Pending
  locked: boolean
  onConfirm: (target: ConfirmTarget) => void
  onPickCluster: () => void
  onFinish: () => void
}

function blockedSentence(code: string, scoreValue: number): string {
  const make = FINISH_BLOCKED_MESSAGES[code as FinishBlock]
  return make ? make(completenessPct(scoreValue)) : code
}

function FinishBlock({ session, locked, finishing, onFinish }: { session: SessionOut; locked: boolean; finishing: boolean; onFinish: () => void }) {
  if (session.status === 'no_candidate') return null
  if (session.status === 'finished') {
    return (
      <Link
        to={`/report/${session.id}`}
        className="inline-flex w-full items-center justify-center gap-1.5 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-contrast hover:bg-primary-hover"
      >
        <FileCheck2 className="h-4 w-4" aria-hidden="true" />
        Open my report
      </Link>
    )
  }
  const { ready, blockedBy, looksLikeTask } = session.finish
  const enabled = ready && !locked
  const reasonId = 'finish-blocked-reason'
  return (
    <div className="flex flex-col gap-2">
      {looksLikeTask && (
        <p className="flex gap-2 rounded border border-primary/30 bg-primary-soft px-3 py-2 text-xs text-link">
          <Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          This looks like a single task rather than a process. You can still finish; the report will say so.
        </p>
      )}
      <Button
        variant="primary"
        className="w-full py-2"
        disabled={!enabled}
        loading={finishing}
        onClick={onFinish}
        aria-describedby={!ready && blockedBy ? reasonId : undefined}
      >
        {finishing ? 'Building your report…' : 'Finish and build my report'}
      </Button>
      {ready ? (
        <p className="text-center text-xs text-subtle">After this, the session is closed.</p>
      ) : (
        blockedBy && (
          <p id={reasonId} className="text-center text-xs text-muted">
            {blockedSentence(blockedBy, session.score.value)}
          </p>
        )
      )}
    </div>
  )
}

export function ProcessProfilePanel({
  session,
  sections,
  onToggleSection,
  activeStep,
  onSelectStep,
  pending,
  locked,
  onConfirm,
  onPickCluster,
  onFinish,
}: Props) {
  const p = session.profile.process
  const active = session.status === 'active' && !locked
  const rows = p.substeps.length
  const declared = p.substep_count ?? rows
  const confirmedCount = Number(p.roles_confirmed) + Number(p.tools_confirmed)

  return (
    <aside
      aria-label="Your process"
      className="flex w-full flex-col gap-3 border-t border-line bg-page p-4 [&>*]:shrink-0 lg:max-w-[480px] lg:flex-[2] lg:overflow-y-auto lg:border-l lg:border-t-0"
    >
      <h2 className="text-base font-semibold text-fg">Your process</h2>

      <ProcessCard
        profile={session.profile}
        fieldViews={session.fieldViews}
        sections={sections}
        onToggle={onToggleSection}
        canPickCluster={active}
        onPickCluster={onPickCluster}
        clusterProposal={session.clusterProposal}
      />

      <section className="overflow-hidden rounded-lg border border-line bg-surface">
        <SectionToggle
          title="Steps"
          count={`${settledStepCount(session.fieldViews, rows)}/${declared}`}
          collapsed={sections.steps.collapsed}
          controls="section-body-steps"
          onToggle={() => onToggleSection('steps')}
        />
        <div id="section-body-steps" hidden={sections.steps.collapsed}>
          <SubstepTabs
            profile={session.profile}
            fieldViews={session.fieldViews}
            activeIndex={activeStep}
            onSelect={onSelectStep}
            sessionActive={active}
            confirming={pending.confirming !== null}
            onNoFurtherSteps={() => onConfirm('substeps')}
          />
        </div>
      </section>

      <section className="overflow-hidden rounded-lg border border-line bg-surface">
        <SectionToggle
          title="Roles and systems"
          count={`${confirmedCount}/2`}
          collapsed={sections.confirm.collapsed}
          controls="section-body-confirm"
          onToggle={() => onToggleSection('confirm')}
        />
        <div id="section-body-confirm" hidden={sections.confirm.collapsed}>
          <DerivedReviewPanel
            roles={p.all_roles}
            tools={p.all_tools}
            rolesConfirmed={p.roles_confirmed}
            toolsConfirmed={p.tools_confirmed}
            confirming={pending.confirming}
            disabled={!active}
            onConfirm={onConfirm}
          />
        </div>
      </section>

      <div className="mt-auto pt-1">
        <FinishBlock session={session} locked={locked} finishing={pending.finishing} onFinish={onFinish} />
      </div>
    </aside>
  )
}
