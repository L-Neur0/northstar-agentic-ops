/**
 * Tests for the phase meter (spec 23 §3.6; AC-23.17, AC-23.18).
 * Why: the meter tells the expert where they are; shown as a strip with the `~`
 * for a step count that is not fixed yet, and a progress bar whose value comes from the server.
 * Rules: colour is a second cue; the percentage text is always shown.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57).
 */
import { render, screen } from '@testing-library/react'
import { DiscoveryPhaseMeter } from './DiscoveryPhaseMeter'
import type { Phase } from '../../types/process-discovery'

const meter = (phase: Phase, over: Partial<Parameters<typeof DiscoveryPhaseMeter>[0]> = {}) =>
  render(
    <DiscoveryPhaseMeter
      phase={phase}
      score={{ value: 0.645, filledPoints: 40, totalPoints: 62 }}
      substepCount={4}
      rows={2}
      activeStep={1}
      {...over}
    />,
  )

describe('DiscoveryPhaseMeter (AC-23.17)', () => {
  it('marks the current phase with aria-current and shows the counter', () => {
    meter('measure')
    expect(screen.getByText('Measures').closest('[aria-current]')).toHaveAttribute('aria-current', 'step')
    expect(screen.getByText('40/62 points · 65 %')).toBeInTheDocument()
    for (const label of ['About you', 'Process', 'Boundaries', 'Step count', 'Steps', 'Confirm', 'Review', 'Finished']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })

  it('shows "step 2 of 4" with P16 set and "step 2 of ~3" without', () => {
    meter('steps')
    expect(screen.getByText('step 2 of 4')).toHaveAttribute('aria-current', 'step')
    meter('steps', { substepCount: null, rows: 3 })
    expect(screen.getByText('step 2 of ~3')).toBeInTheDocument()
  })

  it('on no_candidate mutes the rungs and says it ended', () => {
    meter('no_candidate')
    expect(screen.getByText('Ended: no process to map')).toBeInTheDocument()
    expect(document.querySelector('[aria-current]')).toBeNull()
  })
})

describe('progress bar (AC-23.18)', () => {
  it.each([
    [0.85, 85, 'bg-success'],
    [0.5, 50, 'bg-warning'],
    [0.2, 20, 'bg-primary'],
  ])('score %f → %i %, %s', (value, pct, colour) => {
    meter('measure', { score: { value, filledPoints: 1, totalPoints: 2 } })
    const bar = screen.getByRole('progressbar', { name: 'Completeness' })
    expect(bar).toHaveAttribute('aria-valuenow', String(pct))
    expect(bar).toHaveAttribute('aria-valuemin', '0')
    expect(bar).toHaveAttribute('aria-valuemax', '100')
    expect(screen.getByTestId('progress-fill')).toHaveClass(colour)
    expect(screen.getByText(`1/2 points · ${pct} %`)).toBeInTheDocument()
  })
})
