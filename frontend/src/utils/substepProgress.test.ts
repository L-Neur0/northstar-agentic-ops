/**
 * Tests for the step helpers of the panel (spec 23 §3.8.9–10, AC-23.33).
 * Why: the step tabs and the phase meter both need the active step and a per-step count, read
 * from 1-based cell keys (`process.substeps[1].roles` is step 1, behaviour 6 of spec 23 §5).
 * Rules: only field view statuses decide; S12 is never scored.
 */
import { stepViews } from '../test/fixtures/sessions'
import { activeStepIndex, parseCellKey, settledStepCount, stepScore, viewsForStep } from './substepProgress'

describe('substep progress', () => {
  it('parses 1-based cell keys', () => {
    expect(parseCellKey('process.substeps[1].roles')).toEqual({ step: 1, leaf: 'roles' })
    expect(parseCellKey('process.name')).toBeNull()
  })

  it('scores a step from its S01–S11 views; S12 is not scored', () => {
    const views = [...stepViews(1, 12), ...stepViews(2, 5)]
    expect(stepScore(viewsForStep(views, 1))).toEqual({ filled: 11, total: 11 })
    expect(stepScore(viewsForStep(views, 2))).toEqual({ filled: 5, total: 11 })
    expect(viewsForStep(views, 2)).toHaveLength(12)
  })

  it('picks the first step with an open cell as active (AC-23.33)', () => {
    const views = [...stepViews(1, 12), ...stepViews(2, 5), ...stepViews(3, 0)]
    expect(activeStepIndex(views, 3)).toBe(1)
  })

  it('treats skipped cells as settled and an unscored S12 as irrelevant', () => {
    const views = [...stepViews(1, 10, { exceptions: 'skipped', handover: 'empty' }), ...stepViews(2, 0)]
    expect(activeStepIndex(views, 2)).toBe(1)
  })

  it('returns the last row when every step is settled, and 0 with no rows', () => {
    const views = [...stepViews(1, 12), ...stepViews(2, 11)]
    expect(activeStepIndex(views, 2)).toBe(1)
    expect(activeStepIndex([], 0)).toBe(0)
  })

  it('counts settled steps', () => {
    const views = [...stepViews(1, 12), ...stepViews(2, 5)]
    expect(settledStepCount(views, 2)).toBe(1)
  })
})
