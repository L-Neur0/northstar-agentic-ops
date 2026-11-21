/**
 * Tests for the workspace words and cell text (spec 23 §19.6, §19.8; AC-23.119, AC-23.127).
 * Why: the same status, source and outcome must read the same everywhere, and a grid cell must
 * show the server's text as plain text with "—" for nothing.
 * What: status words and tones, source and outcome words, kind words, `formatCell`, dates.
 * Must not: test rendering (the grid tests do that).
 */
import { formatCell, formatDate, formatDateTime, kindWord, outcomeWord, sourceWord, statusWord, STATUS_TONES } from './workspaceFormat'

describe('formatCell (AC-23.127, Q15: display text from the server)', () => {
  it.each([null, undefined, '', '   '])('%s gives —', (v) => {
    expect(formatCell(v)).toBe('—')
  })
  it('returns the server text unchanged, line breaks and markup included', () => {
    expect(formatCell('SAP\nExcel')).toBe('SAP\nExcel')
    expect(formatCell('<img src=x onerror=alert(1)>')).toBe('<img src=x onerror=alert(1)>')
  })
})

describe('words (§19.8)', () => {
  it('status words match Home and every status has a tone', () => {
    expect(statusWord('active')).toBe('In progress')
    expect(statusWord('finished')).toBe('Mapped')
    expect(statusWord('no_candidate')).toBe('Ended · nothing to map')
    expect(STATUS_TONES).toEqual({ active: 'info', finished: 'success', no_candidate: 'neutral' })
  })
  it('source, outcome and kind words', () => {
    expect(sourceWord('expert')).toBe('expert')
    expect(sourceWord('document')).toBe('from a document')
    expect(sourceWord('specialist')).toBe('specialist')
    expect(sourceWord('agent')).toBe('suggested from the answers')
    expect(sourceWord(null)).toBe('')
    expect(outcomeWord('read')).toBe('read')
    expect(outcomeWord('failed')).toBe('could not be read')
    expect(kindWord('pdf')).toBe('PDF')
    expect(kindWord('odt')).toBe('ODT')
  })
  it('dates in en-GB', () => {
    expect(formatDate('2026-11-20T14:05:00')).toBe('20 Nov 2026')
    expect(formatDateTime('2026-11-20T14:05:00')).toBe('20 Nov 2026, 14:05')
    expect(formatDate('nope')).toBe('')
  })
})
