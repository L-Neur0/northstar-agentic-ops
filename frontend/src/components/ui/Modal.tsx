/**
 * The one dialog primitive of the app (spec 23 §3.9; AC-23.46).
 * Why: one component owns
 * it once: a portal, `role="dialog"` or `alertdialog`, `aria-modal`, labelled by its heading,
 * focus moved in on open, Tab cycling inside, Escape and backdrop close, focus returned to the
 * trigger on close.
 * Rules: with two dialogs mounted only the top one reacts to Escape (a module-level stack);
 * `dismissible={false}` ignores Escape and backdrop and shows no close button (welcome mode, a
 * save in flight). Must not hold any business state.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57).
 */
import { useEffect, useId, useRef, useState, type ReactNode, type RefObject } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'

const stack: string[] = []

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'

interface ModalProps {
  title: ReactNode
  onClose: () => void
  children: ReactNode
  dismissible?: boolean
  role?: 'dialog' | 'alertdialog'
  /** Element to focus on open; default the first focusable element. */
  initialFocusRef?: RefObject<HTMLElement | null>
  icon?: ReactNode
  description?: ReactNode
  footer?: ReactNode
  size?: 'sm' | 'md' | 'lg'
}

const WIDTH = { sm: 'max-w-md', md: 'max-w-lg', lg: 'max-w-2xl' }

export function Modal({
  title,
  onClose,
  children,
  dismissible = true,
  role = 'dialog',
  initialFocusRef,
  icon,
  description,
  footer,
  size = 'md',
}: ModalProps) {
  const id = useId()
  const titleId = `${id}-title`
  const descId = `${id}-desc`
  const panelRef = useRef<HTMLDivElement>(null)
  const onCloseRef = useRef(onClose)
  const dismissibleRef = useRef(dismissible)
  // Captured at first render, before focus moves in, so StrictMode's second effect run cannot
  // replace the trigger with an element inside the dialog.
  const [returnTo] = useState(() => document.activeElement as HTMLElement | null)

  useEffect(() => {
    onCloseRef.current = onClose
    dismissibleRef.current = dismissible
  })

  useEffect(() => {
    stack.push(id)
    const panel = panelRef.current
    const target = initialFocusRef?.current ?? panel?.querySelector<HTMLElement>(FOCUSABLE) ?? panel
    target?.focus()

    const onKeyDown = (e: KeyboardEvent) => {
      if (stack[stack.length - 1] !== id) return
      if (e.key === 'Escape') {
        e.stopPropagation()
        if (dismissibleRef.current) onCloseRef.current()
        return
      }
      if (e.key !== 'Tab' || !panel) return
      const items = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE))
      if (items.length === 0) {
        e.preventDefault()
        return
      }
      const first = items[0]
      const last = items[items.length - 1]
      const active = document.activeElement
      if (e.shiftKey && (active === first || !panel.contains(active))) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && (active === last || !panel.contains(active))) {
        e.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      const at = stack.lastIndexOf(id)
      if (at >= 0) stack.splice(at, 1)
      if (returnTo && document.contains(returnTo)) returnTo.focus()
    }
    // Runs once per mount: focus in on open, out on close.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        data-testid="modal-backdrop"
        className="absolute inset-0 bg-overlay/60"
        onClick={() => {
          if (dismissibleRef.current) onCloseRef.current()
        }}
      />
      <div
        ref={panelRef}
        role={role}
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descId : undefined}
        tabIndex={-1}
        className={`relative flex max-h-[85vh] w-full ${WIDTH[size]} flex-col rounded-lg border border-line bg-surface p-6 shadow-xl focus:outline-none`}
      >
        <div className="mb-3 flex items-center gap-2">
          {icon}
          <h2 id={titleId} className="flex-1 text-lg font-semibold text-fg">
            {title}
          </h2>
          {dismissible && (
            <button
              type="button"
              onClick={onClose}
              aria-label="Close dialog"
              className="rounded p-1 text-subtle hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
            >
              <X className="h-5 w-5" aria-hidden="true" />
            </button>
          )}
        </div>
        {description && (
          <div id={descId} className="mb-4 text-sm text-muted">
            {description}
          </div>
        )}
        <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
        {footer && <div className="mt-4 flex flex-wrap justify-end gap-2">{footer}</div>}
      </div>
    </div>,
    document.body,
  )
}
