/**
 * Button primitive with four variants: primary, secondary, tertiary, danger (spec 23 §4).
 * Why: a plain Tailwind `<button>` that keeps a visible
 * focus ring and a `loading` state with a spinner, so every screen looks and behaves the same.
 * Rules: always a real `<button>` (default `type="button"`); `loading` also disables it and sets
 * `aria-busy`. Must not carry business logic.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57).
 */
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { Spinner } from './Spinner'

export type ButtonVariant = 'primary' | 'secondary' | 'tertiary' | 'danger'

const VARIANT: Record<ButtonVariant, string> = {
  primary: 'bg-primary text-primary-contrast hover:bg-primary-hover disabled:bg-primary/50',
  secondary: 'border border-line-strong bg-surface text-fg hover:bg-surface-muted disabled:text-subtle',
  tertiary: 'text-link underline-offset-2 hover:underline disabled:text-subtle',
  danger: 'bg-danger-solid text-primary-contrast hover:bg-danger-solid-hover disabled:bg-danger-solid/50',
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  loading?: boolean
  icon?: ReactNode
  size?: 'sm' | 'md'
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', loading = false, icon, size = 'md', className = '', disabled, children, type = 'button', ...rest },
  ref,
) {
  const pad = size === 'sm' ? 'px-2.5 py-1 text-xs' : 'px-3 py-1.5 text-sm'
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={`inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed ${pad} ${VARIANT[variant]} ${className}`}
      {...rest}
    >
      {loading ? <Spinner size="sm" /> : icon}
      {children}
    </button>
  )
})
