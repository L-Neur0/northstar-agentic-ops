/**
 * The phase strip and completeness bar under the header (spec 23 §3.6; AC-23.17, AC-23.18).
 * Why: the meter: past and current rungs in the primary colour with a `›`
 * separator, the current rung marked `aria-current="step"`, "step X of Y" on the Steps rung (with
 * `~` while the step count is not fixed), and a bar coloured blue / amber / green.
 * Rules: every number comes from the server (`score.progress`, P16, rows); the percentage text is always
 * shown so colour is never the only cue. Must not compute completeness or progress.
 * Amended 2026-11-21 (owner test; spec 23 §3.6 rules 7–8, AC-23.147, AC-23.148): the bar shows the
 * server's `progress` along the interview path (falls back to `value` from an old server), and a
 * session still stored in `confirm` lights Review as current.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57).
 */
import { PHASE_LABELS, PHASE_STRIP, type Phase, type Score } from '../../types/process-discovery'
import { ProgressBar } from '../ui/ProgressBar'
import { completenessPct } from '../../utils/discoveryFormat'

interface Props {
  phase: Phase
  score: Score
  /** P16 when set. */
  substepCount: number | null
  rows: number
  /** 0-based active step. */
  activeStep: number
}

export function DiscoveryPhaseMeter({ phase, score, substepCount, rows, activeStep }: Props) {
  const ended = phase === 'no_candidate'
  const current = ended ? -1 : PHASE_STRIP.indexOf(phase === 'confirm' ? 'review' : phase)
  const pct = completenessPct(score.progress ?? score.value)
  const colour = pct >= 80 ? 'bg-success' : pct >= 40 ? 'bg-warning' : 'bg-primary'
  const x = activeStep + 1
  const stepText = substepCount ? `step ${x} of ${substepCount}` : `step ${x} of ~${Math.max(rows, x)}`

  return (
    <div className="shrink-0 border-b border-line bg-page px-4 py-2">
      <div className="mb-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs">
        <ol aria-label="Interview progress" className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
          {PHASE_STRIP.map((p, i) => {
            const isCurrent = i === current
            const past = !ended && i <= current
            return (
              <li key={p} className={`flex items-center gap-1.5 ${past ? 'text-link' : 'text-subtle'} ${isCurrent ? 'font-semibold' : ''}`}>
                {i > 0 && <span aria-hidden="true">›</span>}
                <span aria-current={isCurrent ? 'step' : undefined}>
                  {p === 'steps' && phase === 'steps' ? stepText : PHASE_LABELS[p]}
                </span>
              </li>
            )
          })}
        </ol>
        <span className="flex-1" />
        <span className="text-muted">
          {ended ? 'Ended: no process to map' : `${pct} %`}
        </span>
      </div>
      <ProgressBar value={pct} label="Progress" colorClass={colour} />
    </div>
  )
}
