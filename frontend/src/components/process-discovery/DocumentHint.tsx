/**
 * The hint card under the first agent message that invites the expert to add a document (spec 23
 * §11.1; AC-23.73).
 * Why: the welcome message mentions documents (F-04.1); this card is the clickable part of that
 * mention, so starting from a procedure is one press away at the start of the interview.
 * Rules: the page decides when it shows (active, not locked, no documents yet, phase `context` or
 * `find`); its button opens the same file picker as the "+" button. Must not: upload by itself or
 * promise that anything counts before the expert confirms it.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57, AC-23.102).
 */
import { FileText } from 'lucide-react'

export function DocumentHint({ onAdd, disabled }: { onAdd: () => void; disabled: boolean }) {
  return (
    <div className="mx-4 my-2 flex items-start gap-2 rounded-lg border border-primary/30 bg-primary-soft px-3 py-2 text-sm text-fg sm:ml-14">
      <FileText className="mt-0.5 h-4 w-4 shrink-0 text-link" aria-hidden="true" />
      <p>
        Have a procedure, a process map or an example report?{' '}
        <button type="button" onClick={onAdd} disabled={disabled} className="font-semibold text-link underline underline-offset-2 disabled:text-subtle">
          Add a document
        </button>
        . Nothing from it counts until you confirm it.
      </p>
    </div>
  )
}
