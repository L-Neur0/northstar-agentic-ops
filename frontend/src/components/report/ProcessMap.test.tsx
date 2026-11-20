/**
 * Tests for the report's process map (spec 23 §11.12, §11.14.4; AC-23.90, AC-23.91, AC-23.100).
 * Why: the map must follow the app theme, print light, describe itself to a screen reader and
 * fail softly; Mermaid itself never runs in jsdom, so the renderer is a stub that records calls.
 * What: theme by the `dark` class, redraw on toggle, `role="img"` name, "Map as text", failure
 * paths, the simplified caption, and `beforeprint` / `afterprint`.
 * Must not: import Mermaid.
 */
import { act, render, screen, waitFor, within } from '@testing-library/react'
import { ProcessMap, type MapRenderer } from './ProcessMap'
import { euReport, euReportSimplifiedMap, SIMPLIFIED_CAPTION } from '../../test/fixtures/report'

const diagram = euReport.map.diagram

function stub(): MapRenderer & { calls: Array<[string, string, string]> } {
  const calls: Array<[string, string, string]> = []
  const fn = (async (id: string, text: string, theme: string) => {
    calls.push([id, text, theme])
    return `<svg data-theme="${theme}"><g></g></svg>`
  }) as MapRenderer & { calls: typeof calls }
  fn.calls = calls
  return fn
}

afterEach(() => document.documentElement.classList.remove('dark'))

it('draws with the default theme in light mode and exposes the counts (AC-23.90)', async () => {
  const render$ = stub()
  render(<ProcessMap diagram={diagram} caption={null} render={render$} />)
  const img = await screen.findByRole('img', { name: 'Process map: 5 steps across 1 role' })
  expect(img.querySelector('svg')).toHaveAttribute('data-theme', 'default')
  expect(render$.calls[0][1].startsWith('flowchart LR')).toBe(true)
  expect(screen.getByRole('region', { name: 'Process map' })).toHaveAttribute('tabindex', '0')
})

it('uses the dark theme when <html> is dark, and draws again when the theme toggles (AC-23.90)', async () => {
  document.documentElement.classList.add('dark')
  const render$ = stub()
  render(<ProcessMap diagram={diagram} caption={null} render={render$} />)
  await waitFor(() => expect(render$.calls.at(-1)?.[2]).toBe('dark'))
  act(() => document.documentElement.classList.remove('dark'))
  await waitFor(() => expect(render$.calls.at(-1)?.[2]).toBe('default'))
  expect((await screen.findByRole('img')).querySelector('svg')).toHaveAttribute('data-theme', 'default')
})

it('prints in the light theme and goes back to dark after printing (AC-23.100)', async () => {
  document.documentElement.classList.add('dark')
  const render$ = stub()
  render(<ProcessMap diagram={diagram} caption={null} render={render$} />)
  await waitFor(() => expect(render$.calls.at(-1)?.[2]).toBe('dark'))
  act(() => {
    window.dispatchEvent(new Event('beforeprint'))
  })
  await waitFor(() => expect(render$.calls.at(-1)?.[2]).toBe('default'))
  act(() => {
    window.dispatchEvent(new Event('afterprint'))
  })
  await waitFor(() => expect(render$.calls.at(-1)?.[2]).toBe('dark'))
})

it('"Map as text" lists the steps in order with their lane (AC-23.90)', () => {
  render(<ProcessMap diagram={diagram} caption={null} render={stub()} />)
  const details = screen.getByText('Map as text').closest('details') as HTMLElement
  const items = within(details).getAllByRole('listitem')
  expect(items[0]).toHaveTextContent('Step 1 · Collect site spreadsheets (Cost controller)')
  expect(items[4]).toHaveTextContent('Step 5 · Write the variance summary (Cost controller)')
  expect(details).toHaveTextContent('Totals match SAP?: yes, no')
  expect(details.className).toContain('print:hidden')
})

it('says the map could not be drawn when the diagram is null or the renderer throws (AC-23.91)', async () => {
  const { unmount } = render(<ProcessMap diagram={null} caption={null} render={stub()} />)
  expect(screen.getByText('The process map could not be drawn.')).toBeInTheDocument()
  unmount()
  const failing: MapRenderer = async () => {
    throw new Error('parse error')
  }
  render(<ProcessMap diagram={diagram} caption={null} render={failing} />)
  expect(await screen.findByText('The process map could not be drawn.')).toBeInTheDocument()
  expect(screen.queryByRole('img')).not.toBeInTheDocument()
})

it('shows the server caption of a simplified map (AC-23.91)', async () => {
  render(<ProcessMap diagram={euReportSimplifiedMap.map.diagram} caption={euReportSimplifiedMap.map.caption} render={stub()} />)
  expect(screen.getByText(SIMPLIFIED_CAPTION)).toBeInTheDocument()
  await screen.findByRole('img')
})
