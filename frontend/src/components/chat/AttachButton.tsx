/**
 * The round "+" button on the left of the chat message box: the main way to add a document
 * (spec 23 §11.1, product owner decision 2026-11-20; AC-23.103, AC-23.104).
 * Why: experts look at the message box, not at the side panel, so adding a procedure or a process
 * map starts where they already type; it opens the same file picker as the Documents panel.
 * Rules: a real `<button>` with `aria-label="Add a document"`; disabled while a turn is sending,
 * while an upload runs (then it shows a spinner), when the session is closed, or at the document
 * limit, and its tooltip then says why. Must not: read the file or call the API itself.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57, AC-23.102).
 */
import { Plus } from 'lucide-react'
import { Spinner } from '../ui/Spinner'

export const ATTACH_TOOLTIP = 'Add a document: a procedure, a process map or an example report'

export function AttachButton({
  onClick,
  uploading,
  disabledReason,
}: {
  onClick: () => void
  uploading: boolean
  /** Why the button is disabled, or null when it can be pressed. */
  disabledReason: string | null
}) {
  const disabled = uploading || disabledReason !== null
  const title = uploading ? 'A document is being added…' : (disabledReason ?? ATTACH_TOOLTIP)
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label="Add a document"
      title={title}
      aria-busy={uploading || undefined}
      className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-line-strong bg-surface text-fg hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:text-subtle"
    >
      {uploading ? <Spinner size="sm" /> : <Plus className="h-5 w-5" aria-hidden="true" />}
    </button>
  )
}
