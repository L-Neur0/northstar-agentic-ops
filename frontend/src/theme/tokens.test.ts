/**
 * Tests for the colour tokens (spec 23 §3.13.2 and §3.13.6; AC-23.57, AC-23.58).
 * Why: two themes only stay correct if no component paints with a raw Tailwind colour and the
 * token values themselves are readable; both are checked here from the source, not by eye.
 * What: scans every component, page and helper under `src/` for raw palette classes, and reads
 * the CSS variables of `index.css` for `:root` and `.dark` to check WCAG contrast of the pairs.
 * Must not: exempt a file from the scan; a new colour needs a new token, not an exception.
 */
import css from '../index.css?raw'
import { contrastRatio, parseTokens } from './contrast'

const PALETTE =
  'white|black|slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose'
const UTIL = 'bg|text|border(?:-[trblxy])?|ring|ring-offset|divide|outline|from|via|to|fill|stroke|placeholder|accent|shadow|decoration|caret'
const RAW = new RegExp(`(?<![\\w-])(?:${UTIL})-(?:${PALETTE})(?:-\\d{2,3})?(?:/\\d+)?(?![\\w-])`, 'g')

const sources = import.meta.glob(['../**/*.{ts,tsx}', '!../**/*.test.{ts,tsx}'], { query: '?raw', import: 'default', eager: true }) as Record<
  string,
  string
>

describe('no raw colour classes (AC-23.57)', () => {
  it('scans a meaningful set of files', () => {
    expect(Object.keys(sources).length).toBeGreaterThan(20)
  })

  it('the pattern catches the classes it is meant to catch', () => {
    expect('bg-white text-gray-900 bg-blue-600 hover:bg-slate-50 ring-red-200/50'.match(RAW)).toHaveLength(5)
    expect('bg-surface text-muted border-line bg-primary/50 text-current'.match(RAW)).toBeNull()
  })

  it.each(Object.entries(sources))('%s uses only token colours', (_file, text) => {
    expect(text.match(RAW) ?? []).toEqual([])
  })
})

describe('token contrast in both themes (AC-23.58)', () => {
  const light = parseTokens(css, ':root')
  const dark = parseTokens(css, '.dark')

  const PAIRS: Array<[string, string, number]> = [
    ['text', 'bg', 4.5],
    ['text', 'surface', 4.5],
    ['text', 'surface-muted', 4.5],
    ['text-muted', 'bg', 4.5],
    ['text-muted', 'surface', 4.5],
    ['text-subtle', 'surface', 4.5],
    ['link', 'surface', 4.5],
    ['primary-contrast', 'primary', 4.5],
    ['primary-contrast', 'danger-solid', 4.5],
    ['text', 'bubble-expert', 4.5],
    ['text', 'bubble-agent', 4.5],
    ['success', 'surface', 4.5],
    ['warning', 'surface', 4.5],
    ['danger', 'surface', 4.5],
    ['success', 'success-soft', 4.5],
    ['warning', 'warning-soft', 4.5],
    ['danger', 'danger-soft', 4.5],
    ['link', 'primary-soft', 4.5],
    ['primary', 'bg', 3],
  ]

  it('the helper matches known WCAG values', () => {
    expect(contrastRatio('0 0 0', '255 255 255')).toBeCloseTo(21, 5)
    expect(contrastRatio('255 255 255', '255 255 255')).toBeCloseTo(1, 5)
  })

  it.each(PAIRS)('%s on %s meets %s:1', (fg, bg, min) => {
    for (const theme of [light, dark]) {
      expect(theme[fg], `missing --${fg}`).toBeDefined()
      expect(theme[bg], `missing --${bg}`).toBeDefined()
      expect(contrastRatio(theme[fg], theme[bg])).toBeGreaterThanOrEqual(min)
    }
  })

  it('both themes define the same tokens', () => {
    expect(Object.keys(dark).sort()).toEqual(Object.keys(light).sort())
  })
})
