/**
 * Tests for the section counts of the profile panel (spec 23 §3.8.2, AC-23.28, AC-23.31).
 * Why: the client computes no fill rules; the count only tallies field views
 * the server marked `complete`, so a proposed or partial value never counts.
 * Rules: counting, never grading; step cells never land in a process section.
 */
import { processViews, stepViews, view } from '../test/fixtures/sessions'
import { countComplete, sectionHasGaps, sectionViews } from './processFieldScore'

describe('section views and counts', () => {
  const views = [
    ...processViews({ department: 'complete', user_function: 'proposed', region: 'partial' }),
    ...stepViews(1, 12),
  ]

  it('groups process field views by phase and leaves step cells out (AC-23.28)', () => {
    expect(sectionViews(views, 'context').map((v) => v.id)).toEqual(['P01', 'P02', 'P03'])
    expect(sectionViews(views, 'measure')).toHaveLength(6)
    expect(sectionViews(views, 'step_count').map((v) => v.id)).toEqual(['P16'])
  })

  it('counts only complete views; proposed is not counted (AC-23.31)', () => {
    expect(countComplete(sectionViews(views, 'context'))).toEqual({ complete: 1, total: 3 })
  })

  it('reports gaps when any view is not complete', () => {
    expect(sectionHasGaps(sectionViews(views, 'context'))).toBe(true)
    expect(sectionHasGaps([view('department', 'complete')])).toBe(false)
  })
})
