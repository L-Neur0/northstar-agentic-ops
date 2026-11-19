/**
 * Small spinning indicator (spec 23 §4).
 * Why: loading rows, "Thinking…" and busy buttons share one look. It is decorative
 * (`aria-hidden`): the surrounding text or `role="status"` carries the meaning, never the spin.
 * Must not be the only signal that something is happening.
 */
import { LoaderCircle } from 'lucide-react'

export function Spinner({ size = 'md', className = '' }: { size?: 'sm' | 'md'; className?: string }) {
  const dim = size === 'sm' ? 'h-4 w-4' : 'h-5 w-5'
  return <LoaderCircle className={`${dim} animate-spin text-current ${className}`} aria-hidden="true" />
}
