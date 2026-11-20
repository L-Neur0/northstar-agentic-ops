/**
 * Tests for the workspace counts line and session table (spec 23 §19.3; AC-23.116–23.119, AC-23.121).
 * Why: the list is the specialist's overview; it must show the server's counts and order, say
 * clearly when there is nothing (or nothing matching), and open a row by keyboard and mouse.
 * What: the components with fixture rows; role and label queries.
 * Must not: call an API.
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CountsLine, SessionTable } from './SessionTable'
import { reviewList, reviewRow } from '../../test/fixtures/workspace'

const ROWS = [
  reviewRow(),
  reviewRow({ id: 's2', processName: null, department: null, clusterCode: null, clusterName: null, region: null, status: 'active', phase: 'steps' }),
  reviewRow({ id: 's3', processName: 'Laptop onboarding', status: 'no_candidate', phase: 'no_candidate' }),
]

function table(data = reviewList(ROWS), onOpen = vi.fn(), onClearFilters = vi.fn()) {
  render(<SessionTable data={data} busy={false} onOpen={onOpen} onClearFilters={onClearFilters} />)
  return { onOpen, onClearFilters }
}

describe('empty states (AC-23.116)', () => {
  it('no sessions at all', () => {
    table(reviewList([]))
    expect(screen.getByText('No discovery sessions yet.')).toBeInTheDocument()
    expect(screen.queryByRole('table')).toBeNull()
  })
  it('nothing matches the filters, with Clear filters', async () => {
    const { onClearFilters } = table({ ...reviewList([]), counts: { total: 3, active: 1, finished: 1, noCandidate: 1 } })
    expect(screen.getByText('No sessions match these filters.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(onClearFilters).toHaveBeenCalled()
  })
})

describe('counts line (AC-23.117)', () => {
  it('shows the counts; the match part only with a filter; the truncated sentence only when truncated', () => {
    const data = reviewList(ROWS)
    const { rerender } = render(<CountsLine data={data} filtered={false} />)
    expect(screen.getByRole('status')).toHaveTextContent('3 sessions · 1 in progress · 1 mapped · 1 ended with nothing to map')
    expect(screen.getByRole('status')).not.toHaveTextContent('match the filters')
    rerender(<CountsLine data={{ ...data, matching: 2, truncated: true }} filtered />)
    expect(screen.getByRole('status')).toHaveTextContent('2 match the filters')
    expect(screen.getByRole('status')).toHaveTextContent('Showing the 1,000 most recently updated sessions.')
  })
})

describe('table (AC-23.118, AC-23.119)', () => {
  it('has the caption, the eleven columns in order and the rows in server order', () => {
    table()
    const t = screen.getByRole('table', { name: 'Discovery sessions, newest update first' })
    expect(within(t).getAllByRole('columnheader').map((h) => h.textContent)).toEqual([
      'Process', 'Status', 'Department', 'Cluster', 'Region', 'Fields', 'Steps', 'Messages', 'Documents', 'Updated', 'Created',
    ])
    const rows = within(t).getAllByRole('row').slice(1)
    expect(rows.map((r) => within(r).getAllByRole('cell')[0].textContent)).toEqual([
      'Monthly supplier invoice check', 'Not named yet', 'Laptop onboarding',
    ])
    expect(screen.getByRole('region', { name: 'Session list' })).toHaveAttribute('tabindex', '0')
  })

  it('fills gaps with —, shows fields as filled / total, cluster as code · name, created as a date', () => {
    table()
    const [first, second] = screen.getAllByRole('row').slice(1).map((r) => within(r).getAllByRole('cell').map((c) => c.textContent))
    expect(first.slice(2, 6)).toEqual(['Finance', 'FIN · Finance', 'Europe', '52 / 64'])
    expect(first[10]).toBe('18 Nov 2026')
    expect(first[9]).toBe('2 hours ago')
    expect(second.slice(2, 5)).toEqual(['—', '—', '—'])
  })

  it('status is text, with the phase label for active rows', () => {
    table()
    const cells = screen.getAllByRole('row').slice(1).map((r) => within(r).getAllByRole('cell')[1].textContent)
    expect(cells).toEqual(['Mapped', 'In progressSteps', 'Ended · nothing to map'])
  })
})

describe('opening a row (AC-23.121)', () => {
  it('the Process button opens with click, Enter and Space; a click elsewhere on the row too', async () => {
    const { onOpen } = table()
    const user = userEvent.setup()
    const button = screen.getByRole('button', { name: 'Open session Monthly supplier invoice check' })
    await user.click(button)
    button.focus()
    await user.keyboard('{Enter}')
    await user.keyboard(' ')
    await user.click(within(screen.getAllByRole('row')[1]).getByText('Europe'))
    expect(onOpen).toHaveBeenCalledTimes(4)
    expect(onOpen).toHaveBeenLastCalledWith(ROWS[0])
    expect(screen.getByRole('button', { name: 'Open session s2' })).toHaveTextContent('Not named yet')
  })
})

describe('simulated sessions (spec 24 §3.12)', () => {
  it('a seeded evaluation session carries a Simulated tag; a real one does not', () => {
    table(reviewList([reviewRow({ id: 'eval-p01', simulated: true }), reviewRow({ id: 'real' })]))
    const rows = screen.getAllByRole('row').slice(1)
    expect(within(rows[0]).getByText('Simulated')).toBeInTheDocument()
    expect(within(rows[1]).queryByText('Simulated')).toBeNull()
  })
})
