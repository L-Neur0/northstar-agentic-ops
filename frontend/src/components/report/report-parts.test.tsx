/**
 * Tests for the report's part components on the recorded EU report and its variants (spec 23
 * §11.11; AC-23.85, AC-23.87, AC-23.92, AC-23.97, AC-23.98; report v2, amended 2026-11-21:
 * AC-23.153–AC-23.156).
 * Why: each part must show the server's strings in the right structure (tables with captions and
 * scopes, groups in the order sent, notes as warnings or notes) and never turn report text into
 * markup.
 * What: each component rendered alone with a fixture part; the error boundary with a throwing
 * child.
 * Must not: run Mermaid (the map renderer is a stub) or format any value.
 */
import { render, screen, within } from '@testing-library/react'
import { Feasibility, MapAndSteps, QuestionsTable, ReportCover, ReportFields, StepLevelTable, SummarySentences } from './ReportParts'
import { ReportPartBoundary } from './ReportPartBoundary'
import { ReportNoteBox } from './ReportNote'
import { euReport, thinReport } from '../../test/fixtures/report'
import type { MapRenderer } from './ProcessMap'

const stubRender: MapRenderer = async () => '<svg></svg>'

it('the cover shows product, company, process, department, cluster, region, owner, date and the status pill (AC-23.85)', () => {
  render(<ReportCover cover={euReport.cover} />)
  expect(screen.getByText('Discovery report · AI Use Case Discovery Agent · NorthStar Infrastructure Group')).toBeInTheDocument()
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

it('the summary shows each server sentence as its own paragraph, in order (AC-23.153)', () => {
  const { container } = render(<SummarySentences part={euReport.summary} />)
  const paragraphs = Array.from(container.querySelectorAll('p')).map((p) => p.textContent)
  expect(paragraphs).toEqual(euReport.summary.sentences)
  expect(screen.getByText('About 342 hours a year go into this process today: a moderate process.')).toBeInTheDocument()
})

it('an empty summary shows nothing it was not sent (AC-23.153)', () => {
  const { container } = render(<SummarySentences part={thinReport.summary} />)
  expect(container.querySelectorAll('p')).toHaveLength(0)
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

it('a field suggested by the agent labels its quote "suggested from the expert\'s answers" (short step walk)', () => {
  const part = structuredClone(euReport.process)
  part.fields[0] = { ...part.fields[0], source: 'agent', quote: 'I own the merge myself' }
  render(<ReportFields part={part} />)
  expect(screen.getByText("(suggested from the expert's answers)")).toBeInTheDocument()
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
  expect(rows).toHaveLength(part.columns[0].cells.length)
  expect(rows).toHaveLength(13)
  expect(rows[12]).toHaveTextContent('Rules or judgement')
  expect(rows.every((r) => r.getAttribute('scope') === 'row')).toBe(true)
  expect(within(table).getByText('— (skipped)')).toBeInTheDocument()
  expect(within(table).getByText('One view (proposed, not confirmed)')).toBeInTheDocument()
  expect(screen.getByText('Systems used: Outlook, Excel, SAP S/4HANA')).toBeInTheDocument()
  await screen.findByRole('img')
})

it('Part 5 shows step, hours, AI fit as an icon and the server level words, because, route, why and the expert words (AC-23.154)', () => {
  const part = structuredClone(euReport.steps)
  part.rows[4] = { ...part.rows[4], level: null, levelLabel: 'Not assessed', because: [], routeName: 'No route', routeId: null }
  const { container } = render(<StepLevelTable part={part} />)
  const heads = screen.getAllByRole('columnheader').map((h) => h.textContent)
  expect(heads).toEqual(['Step', 'Hours a year', 'AI fit', 'Because', 'Route', 'Why', "The expert's words"])
  const count = (level: string) => part.rows.filter((r) => r.level === level).length
  for (const row of part.rows) expect(screen.getAllByText(row.levelLabel)).toHaveLength(part.rows.filter((r) => r.levelLabel === row.levelLabel).length)
  expect(screen.getByText('Not assessed')).toBeInTheDocument()
  expect(container.querySelectorAll('svg.lucide-signal-high')).toHaveLength(count('strong'))
  expect(container.querySelectorAll('svg.lucide-signal-medium')).toHaveLength(count('partial'))
  expect(container.querySelectorAll('svg.lucide-signal-low')).toHaveLength(count('weak'))
  expect(container.querySelector('svg.lucide-circle-question-mark, svg.lucide-help-circle')).not.toBeNull()
  const step2 = screen.getByText(`Step 2 · ${part.rows[1].name}`).closest('tr') as HTMLElement
  expect(within(step2).getAllByRole('listitem').map((li) => li.textContent)).toEqual(part.rows[1].because)
  expect(within(step2).getByText(part.rows[1].hours)).toBeInTheDocument()
  expect(within(step2).getByText(part.rows[1].routeReason)).toBeInTheDocument()
  expect(screen.getByText('No route')).toBeInTheDocument()
  expect(screen.getAllByText("(the expert's words)").length).toBe(5)
  expect(screen.getByText(/Routes come from a placeholder solution list/)).toBeInTheDocument()
  expect(container.textContent).not.toMatch(/\byes\b|no-go/i)
})

it('the catalogue note is absent when null (AC-23.154)', () => {
  render(<StepLevelTable part={{ ...euReport.steps, catalogueNote: null }} />)
  expect(screen.queryByText(/placeholder solution list/)).not.toBeInTheDocument()
})

it('the three questions: one row each with the question, the server level words and why with the quote (AC-23.155)', () => {
  render(<QuestionsTable questions={euReport.feasibility.questions} />)
  const table = screen.getByRole('table', { name: 'The three questions' })
  expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Question', 'Level', 'Why'])
  const rows = within(table).getAllByRole('rowheader')
  expect(rows.map((r) => r.textContent)).toEqual(euReport.feasibility.questions.map((q) => q.question))
  const questions = euReport.feasibility.questions
  for (const q of questions) expect(within(table).getByText(q.levelLabel)).toBeInTheDocument()
  expect(within(table).getByText('Either can work')).toBeInTheDocument()
  const quoted = questions.filter((q) => q.quote)
  expect(quoted.length).toBeGreaterThan(0)
  for (const q of quoted) expect(within(table).getByText(`“${q.quote}”`)).toBeInTheDocument()
  expect(within(table).getAllByText("(the expert's words)")).toHaveLength(quoted.length)
  expect(table.textContent).not.toMatch(/\byes\b|\bno\b|no-go/i)
})

it('Part 6 shows A the questions, B readiness (dimension, level, to prepare) and footer, C bullets and the gaps line, in order (AC-23.156)', () => {
  const { container } = render(<Feasibility part={euReport.feasibility} />)
  expect(screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)).toEqual([
    'The three questions',
    'Readiness',
    'Before starting and risks',
  ])
  const readiness = screen.getByRole('table', { name: 'Readiness by dimension' })
  expect(within(readiness).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Dimension', 'Level', 'To prepare'])
  expect(within(readiness).getAllByRole('rowheader')).toHaveLength(6)
  expect(within(readiness).getByText('Low')).toBeInTheDocument()
  expect(container.querySelector('svg.lucide-signal-low')).not.toBeNull()
  expect(screen.getByText(/Not a verdict\./)).toBeInTheDocument()
  const bullets = screen.getByRole('list', { name: 'Before starting and risks' })
  expect(within(bullets).getAllByRole('listitem').map((li) => li.textContent)).toEqual(euReport.feasibility.bullets)
  const gaps = screen.getByText(euReport.feasibility.gaps)
  expect(gaps.className).toContain('text-xs')
  const text = container.textContent ?? ''
  expect(text.indexOf('The three questions')).toBeLessThan(text.indexOf('Readiness'))
  expect(text.indexOf('Readiness')).toBeLessThan(text.indexOf(euReport.feasibility.gaps))
})

it('Part 6 nests its block headings one level below the part heading (AC-23.156)', () => {
  render(<Feasibility part={{ ...euReport.feasibility, bullets: [], gaps: '' }} headingLevel={3} />)
  expect(screen.getAllByRole('heading', { level: 4 }).map((h) => h.textContent)).toEqual(['The three questions', 'Readiness'])
  expect(screen.queryByRole('list', { name: 'Before starting and risks' })).toBeNull()
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
  const { container } = render(
    <>
      <SummarySentences part={{ ...euReport.summary, sentences: [evil] }} />
      <Feasibility part={{ ...euReport.feasibility, bullets: [evil] }} />
    </>,
  )
  expect(container.querySelector('img')).toBeNull()
  expect(container.querySelector('strong')).toBeNull()
  expect(container.querySelector('a')).toBeNull()
  expect(screen.getAllByText(evil)).toHaveLength(2)
})
