/**
 * The "Add a document" control of the Documents panel: a button that is also a drop zone (spec 23
 * §11.2, §11.4.1; AC-23.64).
 * Why: an expert can pick a file with the mouse or keyboard, or drop it from the desktop; both must
 * lead to the same upload.
 * Rules: a real `<button>` (Enter and Space press it) that asks the page to open its file picker;
 * a dropped file is handed over as is, and when several are dropped only the first is taken and
 * the caller is told how many came. The zone shows a dashed primary border while a file is dragged
 * over it. Must not: read the file, check limits or call the API.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57, AC-23.102).
 */
import { useState, type DragEvent } from 'react'
import { Upload } from 'lucide-react'

export function FileDrop({
  onOpen,
  onFiles,
  disabled,
}: {
  onOpen: () => void
  onFiles: (files: File[]) => void
  disabled: boolean
}) {
  const [over, setOver] = useState(false)
  const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes('Files')

  return (
    <button
      type="button"
      onClick={onOpen}
      disabled={disabled}
      onDragOver={(e) => {
        if (disabled || !hasFiles(e)) return
        e.preventDefault()
        setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setOver(false)
        if (disabled) return
        const files = Array.from(e.dataTransfer?.files ?? [])
        if (files.length > 0) onFiles(files)
      }}
      className={`flex w-full items-center gap-3 rounded-lg border-2 border-dashed px-3 py-3 text-left text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:text-subtle ${
        over ? 'border-primary bg-primary-soft' : 'border-line-strong bg-surface hover:bg-surface-muted'
      }`}
    >
      <Upload className="h-5 w-5 shrink-0 text-link" aria-hidden="true" />
      <span>
        <span className="block font-medium text-fg">Add a document</span>
        <span className="block text-xs text-muted">or drop a file here</span>
      </span>
    </button>
  )
}
