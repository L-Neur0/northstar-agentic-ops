/**
 * Tests for the step helpers of the panel (spec 23 §3.8.9–10, AC-23.33).
 * Why: the step tabs and the phase meter both need the active step and a per-step count, read
 * from 1-based cell keys (`process.substeps[1].roles` is step 1, behaviour 6 of spec 23 §5).
 * Rules: only field view statuses decide; S12 is never scored; S13 is (short step walk, f/12).
 */
import { stepViews, view } from '../test/fixtures/sessions'
import { activeStepIndex, parseCellKey, settledStepCount, stepScore, viewsForStep } from './substepProgress'

describe('substep progress', () => {
  it('parses 1-based cell keys', () => {
    expect(parseCellKey('process.substeps[1].roles')).toEqual({ step: 1, leaf: 'roles' })
    expect(parseCellKey('process.name')).toBeNull()
  })

  it('scores a step from its S01–S11 and S13 views out of 12; S12 is not scored (AC-23.33)', () => {
    const views = [...stepViews(1, 13), ...stepViews(2, 5)]
    expect(stepScore(viewsForStep(views, 1))).toEqual({ filled: 12, total: 12 })
    expect(stepScore(viewsForStep(views, 2))).toEqual({ filled: 5, total: 12 })
    expect(viewsForStep(views, 2)).toHaveLength(13)
    const noHandover = stepViews(1, 13, { handover: 'empty' })
    expect(stepScore(noHandover)).toEqual({ filled: 12, total: 12 })
  })

  it('returns the thirteen views of a step in registry order, S13 after S12 (AC-23.33)', () => {
    const shuffled = [...stepViews(1, 0)].reverse()
    expect(viewsForStep(shuffled, 1).map((v) => v.id)).toEqual(
      ['S01', 'S02', 'S03', 'S04', 'S05', 'S06', 'S07', 'S08', 'S09', 'S10', 'S11', 'S12', 'S13'],
    )
  })

  it('an open S13 keeps the step unsettled (AC-23.33)', () => {
    const views = [...stepViews(1, 12), ...stepViews(2, 0)]
    expect(activeStepIndex(views, 2)).toBe(0)
  })

  it('picks the first step with an open cell as active (AC-23.33)', () => {
    const views = [...stepViews(1, 13), ...stepViews(2, 5), ...stepViews(3, 0)]
    expect(activeStepIndex(views, 3)).toBe(1)
  })

  it('treats skipped cells as settled and an unscored S12 as irrelevant', () => {
    const views = [...stepViews(1, 13, { exceptions: 'skipped', handover: 'empty' }), ...stepViews(2, 0)]
    expect(activeStepIndex(views, 2)).toBe(1)
  })

  it('returns the last row when every step is settled, and 0 with no rows', () => {
    const views = [...stepViews(1, 13), ...stepViews(2, 13, { handover: 'empty' })]
    expect(activeStepIndex(views, 2)).toBe(1)
    expect(activeStepIndex([], 0)).toBe(0)
  })

  it('counts settled steps', () => {
    const views = [...stepViews(1, 13), ...stepViews(2, 5)]
    expect(settledStepCount(views, 2)).toBe(1)
  })

  it('lists S14 after S13 when the server sends it, never scores it, never keeps a step open (AC-23.151)', () => {
    const views = [...stepViews(1, 13), view('process.substeps[1].decision_criteria', 'empty'), ...stepViews(2, 0)]
    expect(viewsForStep(views, 1).map((v) => v.id).slice(-2)).toEqual(['S13', 'S14'])
    expect(stepScore(viewsForStep(views, 1))).toEqual({ filled: 12, total: 12 })
    expect(activeStepIndex(views, 2)).toBe(1)
  })
})
