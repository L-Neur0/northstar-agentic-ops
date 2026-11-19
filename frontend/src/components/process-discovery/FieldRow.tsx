/**
 * One field of "Your process": status icon and words, label, value, chips (spec 23 §3.8.3–5;
 * AC-23.29–23.31).
 * Why: the server's eight statuses each get a
 * lucide icon with an accessible name and words, so status is never shown by colour alone.
 * Rules: the status comes from the field view and the value from `formatValue`; this row never
 * decides whether something is answered. Proposals show their source and quote (read-only in
 * part 1). Must not render a document's full text.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57).
 */
import type { ReactNode } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  Circle,
  CircleDashed,
  CircleSlash,
  Clock,
  FileText,
  MinusCircle,
  type LucideIcon,
} from 'lucide-react'
import type { FieldStatus, FieldView } from '../../types/process-discovery'

const STATUS: Record<FieldStatus, { Icon: LucideIcon; label: string; colour: string }> = {
  complete: { Icon: CheckCircle2, label: 'Complete', colour: 'text-success' },
  partial: { Icon: CircleDashed, label: 'Partly answered', colour: 'text-warning' },
  invalid: { Icon: AlertTriangle, label: 'Needs a fix', colour: 'text-danger' },
  proposed: { Icon: FileText, label: 'Proposed', colour: 'text-link' },
  skipped: { Icon: MinusCircle, label: 'Skipped', colour: 'text-subtle' },
  deferred: { Icon: Clock, label: 'Asked again later', colour: 'text-warning' },
  given_up: { Icon: CircleSlash, label: 'Left open', colour: 'text-subtle' },
  empty: { Icon: Circle, label: 'Not answered yet', colour: 'text-line-strong' },
}

function Chip({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'info' | 'warning' }) {
  const cls =
    tone === 'info'
      ? 'bg-primary-soft text-link ring-primary/30'
      : tone === 'warning'
        ? 'bg-warning-soft text-warning ring-warning/30'
        : 'bg-surface-muted text-fg ring-line'
  return <span className={`inline-flex rounded px-1.5 py-0.5 text-[0.6875rem] ring-1 ring-inset ${cls}`}>{children}</span>
}

/** Where a proposal came from, its quote and how to confirm it (read-only in part 1). */
export function ProposalChip({ view }: { view: FieldView }) {
  const from = view.source === 'document' ? `from ${view.documentName ?? 'a document'}` : 'from your idea'
  return (
    <div className="mt-1 rounded border border-primary/30 bg-primary-soft/50 px-2 py-1.5 text-xs text-fg">
      <Chip tone="info">{from}</Chip>
      {view.quote && <blockquote className="mt-1 border-l-2 border-primary/50 pl-2 italic">{view.quote}</blockquote>}
      <p className="mt-1 text-muted">Say yes in the chat to confirm, or give the right answer.</p>
    </div>
  )
}

export function FieldRow({ view, value, notScored = false, children }: { view: FieldView; value: string; notScored?: boolean; children?: ReactNode }) {
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
          {view.status === 'proposed' && <Chip tone="info">Proposed</Chip>}
          {view.status === 'deferred' && <Chip tone="warning">Asked again later</Chip>}
          {view.status === 'complete' && view.source === 'document' && <Chip>from {view.documentName ?? 'a document'}</Chip>}
          {view.status === 'complete' && view.source === 'specialist' && <Chip>edited by IT</Chip>}
        </div>
        {view.status === 'proposed' && <ProposalChip view={view} />}
        {children}
      </div>
    </li>
  )
}
