/**
 * A proposed value's source line, its quote and the ✓ / ✎ buttons (spec 23 §11.7; AC-23.75 to
 * AC-23.77).
 * Why: anything read from a document (or an idea) is only a proposal until the expert confirms it
 * (product rule 4), so every proposed row says where it came from, shows the quote on request and
 * offers ✓ (confirm) and ✎ (reject: the agent will ask).
 * Rules: the quote is plain text in a `<blockquote>`, collapsed by default, its open state kept by
 * the page per key so it survives server responses; ✓ / ✎ show only while the session is active
 * and are disabled while another write runs. Must not: count proposals, send a chat message or
 * start a turn, or render the document's text beyond the quote.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57, AC-23.102).
 */
import { useId, useState } from 'react'
import { Check, ChevronDown, ChevronRight, Pencil } from 'lucide-react'
import { Spinner } from '../ui/Spinner'
import type { FieldView } from '../../types/process-discovery'

/** What the panel hands every field row so it can act on proposals. */
export interface ProposalControls {
  /** The session is active and not locked: ✓ and ✎ are shown. */
  canAct: boolean
  /** Another write or a turn is in flight: ✓ and ✎ are disabled. */
  disabled: boolean
  pending: { keys: string[]; kind: 'confirm' | 'reject' } | null
  openQuotes: ReadonlySet<string>
  onToggleQuote: (key: string) => void
  onConfirm: (keys: string[]) => void
  onReject: (key: string, label: string) => void
  /** Names of the session's image documents: their proposals read "(from an image)" (spec 17 §3.19 I5). */
  imageDocuments?: ReadonlySet<string>
}

/** "from <document>", "from <image> (from an image)", "from a removed document" or "from your idea". */
function proposalSource(view: FieldView, images?: ReadonlySet<string>): string {
  if (view.source !== 'document') return 'from your idea'
  if (!view.documentName) return 'from a removed document'
  return images?.has(view.documentName) ? `from ${view.documentName} (from an image)` : `from ${view.documentName}`
}

const ICON_BUTTON =
  'inline-flex h-7 w-7 items-center justify-center rounded-md border border-line-strong bg-surface text-fg hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:text-subtle'

export function ProposalActions({ view, controls }: { view: FieldView; controls?: ProposalControls }) {
  const quoteId = useId()
  const [localOpen, setLocalOpen] = useState(false)
  const open = controls ? controls.openQuotes.has(view.key) : localOpen
  const toggle = () => (controls ? controls.onToggleQuote(view.key) : setLocalOpen((o) => !o))
  const busyKind = controls?.pending?.keys.includes(view.key) ? controls.pending.kind : null

  return (
    <div className="mt-1 text-xs">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="text-link">Proposed · {proposalSource(view, controls?.imageDocuments)}</span>
        {view.quote && (
          <button
            type="button"
            onClick={toggle}
            aria-expanded={open}
            aria-controls={quoteId}
            className="inline-flex items-center gap-0.5 text-link underline underline-offset-2 hover:text-fg"
          >
            {open ? <ChevronDown className="h-3 w-3" aria-hidden="true" /> : <ChevronRight className="h-3 w-3" aria-hidden="true" />}
            {open ? 'Hide quote' : 'Show quote'}
          </button>
        )}
        {controls?.canAct && (
          <span className="ml-auto flex gap-1">
            <button
              type="button"
              className={ICON_BUTTON}
              aria-label={`Confirm ${view.label}`}
              title="Confirm: this is right"
              disabled={controls.disabled}
              aria-busy={busyKind === 'confirm' || undefined}
              onClick={() => controls.onConfirm([view.key])}
            >
              {busyKind === 'confirm' ? <Spinner size="sm" /> : <Check className="h-4 w-4 text-success" aria-hidden="true" />}
            </button>
            <button
              type="button"
              className={ICON_BUTTON}
              aria-label={`Reject ${view.label}`}
              title="Not right: the agent will ask you"
              disabled={controls.disabled}
              aria-busy={busyKind === 'reject' || undefined}
              onClick={() => controls.onReject(view.key, view.label)}
            >
              {busyKind === 'reject' ? <Spinner size="sm" /> : <Pencil className="h-4 w-4" aria-hidden="true" />}
            </button>
          </span>
        )}
      </div>
      {view.quote && (
        <blockquote id={quoteId} hidden={!open} className="mt-1 border-l-2 border-primary/50 pl-2 italic text-muted">
          {view.quote}
        </blockquote>
      )}
    </div>
  )
}
