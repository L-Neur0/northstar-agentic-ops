/**
 * Tests for the report's part components on the recorded EU report and its variants (spec 23
 * §11.11; AC-23.85, AC-23.87, AC-23.92–23.98).
 * Why: each part must show the server's strings in the right structure (tables with captions and
 * scopes, groups in the order sent, notes as warnings or notes) and never turn report text into
 * markup.
 * What: each component rendered alone with a fixture part; the error boundary with a throwing
 * child.
 * Must not: run Mermaid (the map renderer is a stub) or format any value.
 */
import { render, screen, within } from '@testing-library/react'
import {
  AtAGlance,
  GapsAndSources,
  HoursTables,
  MapAndSteps,
  OpportunityList,
  ReadinessTable,
  RecommendedRoute,
  ReportCover,
  ReportFields,
  StepAssessmentTable,
  SuggestedPath,
} from './ReportParts'
import { ReportPartBoundary } from './ReportPartBoundary'
import { ReportNoteBox } from './ReportNote'
import { euReport, thinReport } from '../../test/fixtures/report'
import type { MapRenderer } from './ProcessMap'

const stubRender: MapRenderer = async () => '<svg></svg>'

it('the cover shows product, company, process, department, cluster, region, owner, date and the status pill (AC-23.85)', () => {
  render(<ReportCover cover={euReport.cover} />)
  expect(screen.getByText('Discovery report · Discovery Agent · NorthStar Infrastructure Group')).toBeInTheDocument()
  expect(screen.getByRole('heading', { level: 2, name: 'Monthly cost review' })).toBeInTheDocument()
  for (const [term, value] of [
    ['Department', 'Finance'],
    ['Cluster', 'FIN · Finance'],
    ['Region', 'Europe'],
    ['Process owner', 'Head of Controlling'],
    ['Date', '19 November 2026'],
  ]) {
    expect(screen.getByText(term).nextElementSibling).toHaveTextContent(value)
  }
  expect(screen.getByText('Mapped')).toBeInTheDocument()
  render(<ReportCover cover={{ ...euReport.cover, status: 'Validated by IT' }} />)
  expect(screen.getByText('Validated by IT')).toBeInTheDocument()
})

it('At a glance shows the hours, the route headline, three top opportunities with hours and To prepare', () => {
  render(<AtAGlance part={euReport.atAGlance} />)
  expect(screen.getByText('About 342 hours a year.')).toBeInTheDocument()
  expect(screen.getByText(/^Start with step 2/)).toBeInTheDocument()
  expect(screen.getByText('Read the site spreadsheets into the master file · Steps 1–2 · 168 h')).toBeInTheDocument()
  expect(screen.getByText('Chase variance explanations automatically · Step 4 · 30 h')).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'To prepare' })).toBeInTheDocument()
})

it('Parts 2 and 3 render <dl> pairs with the server values, and the notes (AC-23.87)', () => {
  const { container } = render(<ReportFields part={euReport.process} />)
  expect(container.querySelector('dl')).not.toBeNull()
  expect(screen.getByText('Trigger').nextElementSibling).toHaveTextContent('Month-end close is completed in SAP')
  render(<ReportFields part={{ ...thinReport.measures, notes: [{ kind: 'task', text: 'This looks like a single task.' }] }} />)
  expect(screen.getAllByText('Not measured yet').length).toBeGreaterThan(0)
  expect(screen.getByText('This looks like a single task.')).toBeInTheDocument()
  const eu = render(<ReportFields part={euReport.measures} />)
  expect(within(eu.container).getByText('Sensitive data or regulation').nextElementSibling).toHaveTextContent('None')
})

it('the step table has a caption, a column header per step and a row header per leaf, in a focusable region (AC-23.92)', async () => {
  const part = structuredClone(euReport.map)
  part.columns[0].cells[1] = { ...part.columns[0].cells[1], value: '— (skipped)' }
  part.columns[1].cells[1] = { ...part.columns[1].cells[1], value: 'One view (proposed, not confirmed)' }
  render(<MapAndSteps part={part} render={stubRender} />)
  const region = screen.getByRole('region', { name: 'Step table' })
  expect(region).toHaveAttribute('tabindex', '0')
  const table = within(region).getByRole('table')
  expect(within(table).getByText('Steps of the process, one column per step').tagName).toBe('CAPTION')
  const cols = within(table).getAllByRole('columnheader')
  expect(cols.slice(1).map((c) => c.textContent)).toEqual(part.columns.map((c) => `Step ${c.number} · ${c.name}`))
  expect(cols.every((c) => c.getAttribute('scope') === 'col')).toBe(true)
  const rows = within(table).getAllByRole('rowheader')
  expect(rows).toHaveLength(12)
  expect(rows.every((r) => r.getAttribute('scope') === 'row')).toBe(true)
  expect(within(table).getByText('— (skipped)')).toBeInTheDocument()
  expect(within(table).getByText('One view (proposed, not confirmed)')).toBeInTheDocument()
  expect(screen.getByText('Systems used: Outlook, Excel, SAP S/4HANA')).toBeInTheDocument()
  await screen.findByRole('img')
})

it('Part 5 has the seven columns, an icon and the server word for AI fit, routes and evidence as sent, and the catalogue note (AC-23.93)', () => {
  const part = structuredClone(euReport.steps)
  part.rows[4] = { ...part.rows[4], fit: null, fitLabel: 'Not assessed', routeName: 'No route', routeId: null }
  const { container } = render(<StepAssessmentTable part={part} />)
  const heads = screen.getAllByRole('columnheader').map((h) => h.textContent)
  expect(heads).toEqual(['Step', 'Hours a year', 'AI fit', 'Route', 'Why this route', 'Reason', 'Evidence'])
  expect(screen.getAllByText('AI can do it')).toHaveLength(3)
  expect(screen.getByText('Not assessed')).toBeInTheDocument()
  expect(screen.getByText('No route')).toBeInTheDocument()
  expect(container.querySelectorAll('svg.lucide-bot')).toHaveLength(3)
  expect(container.querySelector('svg.lucide-circle-question-mark, svg.lucide-help-circle')).not.toBeNull()
  expect(screen.getAllByText("(the expert's words)").length).toBe(5)
  expect(screen.getByText(/Routes come from a placeholder solution list/)).toBeInTheDocument()
})

it('the catalogue note is absent when null (AC-23.93)', () => {
  render(<StepAssessmentTable part={{ ...euReport.steps, catalogueNote: null }} />)
  render(<RecommendedRoute part={{ ...euReport.route, catalogueNote: null }} />)
  expect(screen.queryByText(/placeholder solution list/)).not.toBeInTheDocument()
})

it('Part 6 shows the headline, the groups in the order sent and What to have in place (AC-23.94)', () => {
  render(<RecommendedRoute part={euReport.route} />)
  expect(screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)).toEqual(['Start with', 'Later', 'Fix first', 'What to have in place'])
  expect(screen.getByText('Step 1 · Collect site spreadsheets · The layouts must be agreed before any tool can read them.')).toBeInTheDocument()
  expect(screen.getByText('Step 4 · Chase explanations · 30 h · Low-code workflow automation')).toBeInTheDocument()
})

it('Part 10 shows its three groups in order and "Nothing here." as sent (AC-23.94)', () => {
  render(<SuggestedPath part={euReport.path} />)
  expect(screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)).toEqual(['Prepare first', 'Quick wins', 'Bigger changes'])
  expect(screen.getByText('Nothing here.')).toBeInTheDocument()
  expect(screen.getByText('Draft the variance summary · Step 5: Write the variance summary · 72 h')).toBeInTheDocument()
})

it('Part 7 shows every opportunity with its labels, sections, evidence and the stay-with-people list (AC-23.95)', () => {
  render(<OpportunityList part={euReport.assessment} />)
  const articles = screen.getAllByRole('article')
  expect(articles).toHaveLength(4)
  const first = articles[0]
  expect(within(first).getByRole('heading', { name: 'Read the site spreadsheets into the master file' })).toBeInTheDocument()
  expect(first).toHaveTextContent('Steps 1–2: Collect site spreadsheets, Consolidate into the master file · Document AI · Impact High · Feasibility Medium')
  for (const term of ['What changes', 'How', 'Prepare first', 'Why this impact', 'Why this feasibility', 'Evidence']) {
    expect(within(first).getByText(term)).toBeInTheDocument()
  }
  expect(within(first).getByText(/I copy the numbers into the master file by hand/)).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Steps that stay with people' })).toBeInTheDocument()
  expect(screen.getByText(/The commentary to the CFO is the controller's judgement/)).toBeInTheDocument()
})

it('Part 8 renders both tables, the total in tfoot, formulas, assumptions and the parked line (AC-23.96)', () => {
  const { container } = render(<HoursTables part={euReport.potential} />)
  expect(container.querySelector('tfoot')).toHaveTextContent('Total342 h')
  expect(screen.getByRole('table', { name: /Hours a year per step/ })).toBeInTheDocument()
  expect(screen.getByRole('table', { name: /each opportunity touches/ })).toHaveTextContent('Read the site spreadsheets into the master file')
  expect(screen.getByText('Hours a year: 72 + 96 + 72 + 30 + 72 = 342 h')).toBeInTheDocument()
  expect(screen.getByText(/A working year is taken as 50 weeks/)).toBeInTheDocument()
  expect(screen.getByTestId('parked-line')).toHaveTextContent(euReport.potential.parkedLine)
})

it('Part 8 shows "—" as sent when incomplete (AC-23.96)', () => {
  const part = { ...euReport.potential, complete: false, totals: { hours: '—' } }
  const { container } = render(<HoursTables part={part} />)
  expect(container.querySelector('tfoot')).toHaveTextContent('Total—')
})

it('Part 9 renders six rows with level words and the "Not a verdict" footer (AC-23.96)', () => {
  const { container } = render(<ReadinessTable part={euReport.readiness} />)
  expect(within(screen.getByRole('table')).getAllByRole('rowheader')).toHaveLength(6)
  expect(screen.getAllByText('High').length).toBeGreaterThan(0)
  expect(screen.getByText('Low')).toBeInTheDocument()
  expect(container.querySelector('svg.lucide-signal-low')).not.toBeNull()
  expect(screen.getByText(/Not a verdict\./)).toBeInTheDocument()
})

it('Part 11 lists open fields, documents with outcome words (no text) and the closing note (AC-23.96)', () => {
  const part = {
    ...euReport.gaps,
    fields: [{ key: 'process.target_metric', label: 'Target', value: 'Left open', status: 'given_up' as const, source: null, quote: null }],
    documents: [{ name: 'procedure.docx', outcome: 'read' }, { name: 'scan.pdf', outcome: 'could not be read' }],
  }
  render(<GapsAndSources part={part} />)
  expect(screen.getByText('Target: Left open')).toBeInTheDocument()
  expect(screen.getByText('procedure.docx · read')).toBeInTheDocument()
  expect(screen.getByText('scan.pdf · could not be read')).toBeInTheDocument()
  expect(screen.getByText(/This is a first assessment from one expert's account/)).toBeInTheDocument()
})

it('notes: failed and error are warnings, other kinds are notes, always with the server text (AC-23.97)', () => {
  render(
    <>
      <ReportNoteBox kind="failed" text="The opportunities could not be generated this time." />
      <ReportNoteBox kind="simplified" text="The map is simplified." />
    </>,
  )
  expect(screen.getByText('The opportunities could not be generated this time.').parentElement).toHaveTextContent(/^Warning: /)
  expect(screen.getByText('The map is simplified.').parentElement).toHaveTextContent(/^Note: /)
})

it('a part that throws is caught by its boundary; siblings still render (AC-23.97)', () => {
  const error = vi.spyOn(console, 'error').mockImplementation(() => {})
  function Boom(): never {
    throw new TypeError('bad part')
  }
  render(
    <>
      <ReportPartBoundary fallback={<p>This part could not be shown.</p>}>
        <Boom />
      </ReportPartBoundary>
      <p>Next part</p>
    </>,
  )
  expect(screen.getByText('This part could not be shown.')).toBeInTheDocument()
  expect(screen.getByText('Next part')).toBeInTheDocument()
  expect(error).toHaveBeenCalledWith('report part failed to render:', 'TypeError')
  error.mockRestore()
})

it('report text with HTML or Markdown is shown as literal text (AC-23.98)', () => {
  const evil = '<img src=x onerror=alert(1)> **bold** [link](http://x)'
  const { container } = render(<AtAGlance part={{ ...euReport.atAGlance, hours: evil, prepare: [evil] }} />)
  expect(container.querySelector('img')).toBeNull()
  expect(container.querySelector('strong')).toBeNull()
  expect(container.querySelector('a')).toBeNull()
  expect(screen.getAllByText(evil)).toHaveLength(2)
})
