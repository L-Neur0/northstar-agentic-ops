/**
 * The four summary cards at the top of the workspace popup (spec 23 §19.4 block 1; AC-23.124).
 * Why: before the details, the specialist sees who told the process, what it is, how much of it
 * is mapped and how big the conversation was, in four short cards.
 * Rules: each card is a `<section>` labelled by its `<h3>` with a `<dl>`; completeness is the
 * server's score shown as a whole percent; every empty value shows "—"; 4 columns from 1024 px,
 * 2 from 640 px, else 1. Must not: compute a score or a status.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.141).
 */
import { useId } from 'react'
import { completenessPct, phaseLabel } from '../../utils/discoveryFormat'
import { orDash, statusWord } from '../../utils/workspaceFormat'
import type { ReviewSummary } from '../../types/workspace'

function Card({ title, items }: { title: string; items: Array<[string, string]> }) {
  const id = useId()
  return (
    <section aria-labelledby={id} className="rounded-md border border-line bg-surface-muted p-3">
      <h3 id={id} className="mb-2 text-sm font-semibold text-fg">
        {title}
      </h3>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
        {items.map(([term, value]) => (
          <div key={term} className="contents">
            <dt className="text-muted">{term}</dt>
            <dd className="min-w-0 break-words text-fg">{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

export function SummaryCards({ summary: s }: { summary: ReviewSummary }) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Card
        title="Context"
        items={[
          ['Department', orDash(s.department)],
          ['Function', orDash(s.function)],
          ['Region', orDash(s.region)],
        ]}
      />
      <Card
        title="Process"
        items={[
          ['Name', orDash(s.processName)],
          ['Cluster', orDash(s.clusterName)],
          ['Status', statusWord(s.status)],
          ['Phase', phaseLabel(s.phase)],
        ]}
      />
      <Card
        title="Scope"
        items={[
          ['Fields filled', `${s.fieldsFilled} / ${s.fieldsTotal}`],
          ['Steps', `${s.stepsStarted} / ${s.stepsExpected}`],
        ]}
      />
      <Card
        title="Measures"
        items={[
          ['Completeness', `${completenessPct(s.completeness)} %`],
          ['Points', `${s.filledPoints} / ${s.totalPoints}`],
          ['Messages', String(s.messageCount)],
          ['Documents', String(s.documentCount)],
        ]}
      />
    </div>
  )
}
