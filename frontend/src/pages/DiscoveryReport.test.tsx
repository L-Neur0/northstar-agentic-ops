/**
 * Page tests for the discovery report (spec 23 §11.10–§11.14; AC-23.82–23.84, AC-23.86, AC-23.97,
 * AC-23.99, AC-23.100).
 * Why: the page is the expert's result; it must load once, explain a report that is not ready,
 * show the cover and eleven parts in order with a contents nav, never show a euro figure, survive
 * a missing part, download the PDF with the visitor key, and hide its chrome when printed.
 * What: the real page through the router with an injected API (the fake, or stubs) and a stub map
 * renderer.
 * Must not: run Mermaid or start a real download.
 */
import { StrictMode } from 'react'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router-dom'
import { DiscoveryReport } from './DiscoveryReport'
import { renderWithProviders } from '../test/render'
import { createFakeApi } from '../services/fakeApi'
import { ApiError, type DiscoveryApi } from '../services/api'
import { euReport, euReportStepsFailed, STEPS_FAILED_TEXT } from '../test/fixtures/report'
import type { MapRenderer } from '../components/report/ProcessMap'
import type { DiscoveryReport as Report } from '../types/report'

const stubMap: MapRenderer = async () => '<svg></svg>'

function api(report: () => Promise<Report>): DiscoveryApi {
  const a = createFakeApi({ delayMs: 0, persist: false })
  vi.spyOn(a, 'getReport').mockImplementation(report)
  return a
}

function open(a: DiscoveryApi, strict = false) {
  const page = (
    <Routes>
      <Route path="/report/:sessionId" element={<DiscoveryReport mapRenderer={stubMap} />} />
      <Route path="*" element={<p>elsewhere</p>} />
    </Routes>
  )
  return renderWithProviders(strict ? <StrictMode>{page}</StrictMode> : page, { api: a, route: '/report/s-1' })
}

const TITLES = [
  '1. At a glance',
  '2. The process',
  '3. Volume and measures',
  '4. Process map and steps',
  '5. Step-by-step AI assessment',
  '6. Recommended route',
  '7. Transformation assessment',
  '8. Hours a year',
  '9. Readiness checklist',
  '10. Suggested path',
  '11. Gaps and sources',
]

afterEach(() => vi.restoreAllMocks())

it('calls GET report once under StrictMode, shows the loading status, then the report (AC-23.82)', async () => {
  let resolve!: (r: Report) => void
  const a = api(() => new Promise((r) => (resolve = r)))
  open(a, true)
  expect(screen.getByRole('status')).toHaveTextContent('Loading your report…')
  resolve(euReport)
  expect(await screen.findByText('About 342 hours a year.')).toBeInTheDocument()
  expect(a.getReport).toHaveBeenCalledTimes(1)
  expect(a.getReport).toHaveBeenCalledWith('s-1')
})

it.each([
  ['404', new ApiError(404, 'not_found', 'Not found.')],
  ['409 report_not_ready', new ApiError(409, 'report_not_ready', 'The report is ready once the map is finished.')],
])('%s says the report is not available, with the two ways on (AC-23.83)', async (_name, error) => {
  open(api(() => Promise.reject(error)))
  expect(await screen.findByText('This report is not available. A report is ready once the interview is finished.')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Continue the interview' })).toHaveAttribute('href', '/process-discovery/s-1')
  expect(screen.getAllByRole('link', { name: 'Back to My processes' }).length).toBeGreaterThan(0)
})

it('any other error shows its sentence and Retry refetches (AC-23.83)', async () => {
  const user = userEvent.setup()
  const get = vi.fn().mockRejectedValueOnce(new ApiError(0, 'network', 'x')).mockResolvedValueOnce(euReport)
  const a = api(get)
  open(a)
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not reach the server. Check your connection and try again.')
  await user.click(screen.getByRole('button', { name: 'Retry' }))
  expect(await screen.findByText('About 342 hours a year.')).toBeInTheDocument()
  expect(get).toHaveBeenCalledTimes(2)
})

it('renders the cover, then eleven sections in order, linked from the contents nav (AC-23.84)', async () => {
  open(api(async () => euReport))
  await screen.findByText('About 342 hours a year.')
  const sections = document.querySelectorAll('article section[aria-labelledby]')
  expect(sections).toHaveLength(11)
  expect(Array.from(sections).map((s) => s.querySelector('h2')?.textContent)).toEqual(TITLES)
  expect(screen.getByRole('heading', { level: 2, name: 'Monthly cost review' })).toBeInTheDocument()
  const nav = screen.getByRole('navigation', { name: 'Report contents' })
  const links = within(nav).getAllByRole('link')
  expect(links.map((l) => l.getAttribute('href'))).toEqual([
    '#part-at_a_glance',
    '#part-process',
    '#part-measures',
    '#part-map',
    '#part-steps',
    '#part-route',
    '#part-assessment',
    '#part-potential',
    '#part-readiness',
    '#part-path',
    '#part-gaps',
  ])
  expect(document.getElementById('part-at_a_glance')).toBe(sections[0])
})

it('shows the hours, the route headline and three top opportunities, and no euro, cost or saving (AC-23.86)', async () => {
  const { container } = open(api(async () => euReport))
  await screen.findByText('About 342 hours a year.')
  expect(screen.getAllByText(/^Start with step 2 "Consolidate into the master file"/).length).toBeGreaterThan(0)
  for (const hours of ['Steps 1–2 · 168 h', 'Step 5 · 72 h', 'Step 4 · 30 h']) expect(screen.getByText(new RegExp(hours))).toBeInTheDocument()
  // The server's own "parked" sentence explains that euro values are not shown yet (R5); it is
  // the only place money is mentioned, so the scan runs on the page without it.
  const clone = container.cloneNode(true) as HTMLElement
  clone.querySelector('[data-testid="parked-line"]')?.remove()
  const text = clone.textContent ?? ''
  for (const word of ['€', 'cost today', 'freed', 'saving']) expect(text.toLowerCase()).not.toContain(word.toLowerCase())
})

it('a failed part shows the warning, a missing part its fallback heading, and the rest still renders (AC-23.97)', async () => {
  const broken = structuredClone(euReportStepsFailed) as unknown as Record<string, unknown>
  delete broken.map
  open(api(async () => broken as unknown as Report))
  await screen.findByText('About 342 hours a year.')
  const steps = document.getElementById('part-steps') as HTMLElement
  expect(within(steps).getByText(STEPS_FAILED_TEXT).parentElement).toHaveTextContent(/^Warning:/)
  const map = document.getElementById('part-map') as HTMLElement
  expect(within(map).getByRole('heading', { level: 2 })).toHaveTextContent('4. Process map and steps')
  expect(within(map).getByText('This part could not be generated.')).toBeInTheDocument()
  expect(document.querySelectorAll('article section[aria-labelledby]')).toHaveLength(11)
  expect(screen.getByRole('heading', { level: 2, name: '11. Gaps and sources' })).toBeInTheDocument()
})

it('Download PDF fetches once, shows "Preparing PDF…", saves under the file name and revokes the URL (AC-23.99)', async () => {
  const user = userEvent.setup()
  const a = api(async () => euReport)
  let finish!: (v: { blob: Blob; filename: string }) => void
  const pdf = vi.spyOn(a, 'getReportPdf').mockImplementation(() => new Promise((r) => (finish = r)))
  const create = vi.fn(() => 'blob:pdf')
  const revoke = vi.fn()
  Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke })
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  open(a)
  await screen.findByText('About 342 hours a year.')
  await user.click(screen.getAllByRole('button', { name: 'Download PDF' })[0])
  expect(screen.getAllByRole('button', { name: /Preparing PDF…|Download PDF/ })[0]).toBeDisabled()
  expect(screen.getByText('Preparing PDF…')).toBeInTheDocument()
  finish({ blob: new Blob(['%PDF']), filename: 'discovery-report-monthly-cost-review.pdf' })
  await waitFor(() => expect(revoke).toHaveBeenCalledWith('blob:pdf'))
  expect(pdf).toHaveBeenCalledTimes(1)
  expect((click.mock.contexts[0] as HTMLAnchorElement).download).toBe('discovery-report-monthly-cost-review.pdf')
})

it('a PDF error shows inline next to the button and leaves the report visible (AC-23.99)', async () => {
  const user = userEvent.setup()
  const a = api(async () => euReport)
  vi.spyOn(a, 'getReportPdf').mockRejectedValue(new ApiError(404, 'not_found', 'Not found.'))
  open(a)
  await screen.findByText('About 342 hours a year.')
  await user.click(screen.getAllByRole('button', { name: 'Download PDF' })[0])
  expect(await screen.findByRole('alert')).toHaveTextContent('This report is not available.')
  expect(screen.getByText('About 342 hours a year.')).toBeInTheDocument()
})

it('print hides the header, the contents nav and the buttons (AC-23.100)', async () => {
  open(api(async () => euReport))
  await screen.findByText('About 342 hours a year.')
  expect(screen.getByTestId('report-header').className).toContain('print:hidden')
  expect(screen.getByRole('navigation', { name: 'Report contents' }).closest('aside')?.className).toContain('print:hidden')
  for (const button of screen.getAllByRole('button', { name: 'Download PDF' })) {
    expect(button.closest('.print\\:hidden')).not.toBeNull()
  }
})
