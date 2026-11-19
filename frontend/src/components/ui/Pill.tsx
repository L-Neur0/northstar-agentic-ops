/**
 * Status pill with five tones: neutral, info, success, warning, danger (spec 23 §4).
 * Why: Home, the sessions dialog and the panel mark status with a small coloured label.
 * Rules: the pill always carries text; colour is only a second cue (spec 23 §5 behaviour 16).
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57).
 */
import type { ReactNode } from 'react'

export type PillTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger'

const TONE: Record<PillTone, string> = {
  neutral: 'bg-surface-muted text-fg ring-line',
  info: 'bg-primary-soft text-link ring-primary/30',
  success: 'bg-success-soft text-success ring-success/30',
  warning: 'bg-warning-soft text-warning ring-warning/30',
  danger: 'bg-danger-soft text-danger ring-danger/30',
}

export function Pill({ tone = 'neutral', children }: { tone?: PillTone; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${TONE[tone]}`}>
      {children}
    </span>
  )
}
