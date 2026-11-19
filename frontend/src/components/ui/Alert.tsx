/**
 * Banner for errors and notices (spec 23 §3.11, §3.3).
 * Why: the interview page shows one dismissible error banner under the phase meter, and Home shows
 * one-time notices; both need an icon, text and an optional close button.
 * Rules: errors use `role="alert"`, notices `role="status"`; the tone is never the only cue (an
 * icon and text always come with it). Must not render the visitor key or the expert's text.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57).
 */
import type { ReactNode } from 'react'
import { AlertTriangle, Info, X } from 'lucide-react'

export function Alert({
  tone = 'error',
  children,
  onClose,
}: {
  tone?: 'error' | 'info'
  children: ReactNode
  onClose?: () => void
}) {
  const isError = tone === 'error'
  return (
    <div
      role={isError ? 'alert' : 'status'}
      className={`flex items-start gap-2 border-b px-4 py-2 text-sm ${
        isError ? 'border-danger/30 bg-danger-soft text-danger' : 'border-primary/30 bg-primary-soft text-link'
      }`}
    >
      {isError ? (
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      ) : (
        <Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      )}
      <div className="flex-1">{children}</div>
      {onClose && (
        <button type="button" onClick={onClose} aria-label="Dismiss" className="rounded p-0.5 hover:bg-fg/5">
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      )}
    </div>
  )
}
