/**
 * One field of "Your process": status icon and words, label, value, chips (spec 23 §3.8.3–5,
 * §11.7; AC-23.29–23.31, AC-23.75).
 * Why: the server's eight statuses each get a
 * lucide icon with an accessible name and words, so status is never shown by colour alone.
 * Rules: the status comes from the field view and the value from `formatValue`; this row never
 * decides whether something is answered. Proposals show their source, the quote on request and
 * ✓ / ✎ (`ProposalActions`, part 2). A field (or step cell) with an open conflict shows the chip
 * "Conflict – answer in the chat" and no button: the expert settles it in the chat (spec 23 §11.7,
 * amended 2026-11-20; AC-23.146). A value proposed from the expert's answers (source `agent`, short
 * step walk) shows "suggested from your answers", like a document's file name, before and after
 * the expert's yes. Must not render a document's full text.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57).
 */
import type { ReactNode } from 'react'
import type { FieldView } from '../../types/process-discovery'
import { STATUS } from './fieldStatus'
import { AGENT_SOURCE, ProposalActions, type ProposalControls } from './ProposalActions'

function Chip({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'info' | 'warning' }) {
  const cls =
    tone === 'info'
      ? 'bg-primary-soft text-link ring-primary/30'
      : tone === 'warning'
        ? 'bg-warning-soft text-warning ring-warning/30'
        : 'bg-surface-muted text-fg ring-line'
  return <span className={`inline-flex rounded px-1.5 py-0.5 text-[0.6875rem] ring-1 ring-inset ${cls}`}>{children}</span>
}

export function FieldRow({
  view,
  value,
  notScored = false,
  proposals,
  children,
}: {
  view: FieldView
  value: string
  notScored?: boolean
  proposals?: ProposalControls
  children?: ReactNode
}) {
  const { Icon, label, colour } = STATUS[view.status] ?? STATUS.empty
  const showValue = value.trim().length > 0
  const empty = <span className="italic text-subtle">Not yet described</span>

  let body: ReactNode
  switch (view.status) {
    case 'skipped':
      body = <span className="italic text-subtle">Skipped</span>
      break
    case 'given_up':
      body = <span className="italic text-subtle">Left open</span>
      break
    case 'empty':
      body = empty
      break
    default:
      body = showValue ? <span className="break-words text-fg">{value}</span> : empty
  }

  return (
    <li className="flex items-start gap-2 border-t border-line py-1.5 first:border-t-0">
      <Icon role="img" aria-label={label} className={`mt-0.5 h-4 w-4 shrink-0 ${colour}`} />
      <div className="min-w-0 flex-1 text-sm">
        <div className="text-xs font-medium text-muted">
          <span data-field-label>{view.label}</span>
          {notScored && <span className="ml-1 font-normal text-subtle">(not scored)</span>}
        </div>
        <div>{body}</div>
        {(view.status === 'partial' || view.status === 'invalid') && view.reason && (
          <p className={`text-xs ${view.status === 'invalid' ? 'text-danger' : 'text-warning'}`}>{view.reason}</p>
        )}
        <div className="mt-0.5 flex flex-wrap gap-1 empty:hidden">
          {view.status === 'deferred' && <Chip tone="warning">Asked again later</Chip>}
          {view.conflict === 'open' && <Chip tone="warning">Conflict – answer in the chat</Chip>}
          {view.status === 'complete' && view.source === 'document' && <Chip>from {view.documentName ?? 'a removed document'}</Chip>}
          {view.status === 'complete' && view.source === 'specialist' && <Chip>edited by IT</Chip>}
          {view.status === 'complete' && view.source === 'agent' && <Chip>{AGENT_SOURCE}</Chip>}
        </div>
        {view.status === 'proposed' && <ProposalActions view={view} controls={proposals} />}
        {children}
      </div>
    </li>
  )
}
