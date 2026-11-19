/**
 * Accessible progress bar (spec 23 §3.6.6; AC-23.18).
 * Why: the completeness bar of the phase meter. It exposes `role="progressbar"` with
 * `aria-valuenow/min/max` and a label; the value comes from the server.
 * Rules: colour is a second cue only; the caller always shows the percentage as text.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57).
 */
export function ProgressBar({ value, label, colorClass }: { value: number; label: string; colorClass: string }) {
  const pct = Math.max(0, Math.min(100, value))
  return (
    <div
      role="progressbar"
      aria-valuenow={pct}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
      className="h-1.5 w-full overflow-hidden rounded-full bg-surface-strong"
    >
      <div data-testid="progress-fill" className={`h-full transition-[width] duration-500 ${colorClass}`} style={{ width: `${pct}%` }} />
    </div>
  )
}
