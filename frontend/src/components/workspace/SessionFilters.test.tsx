/**
 * Tests for the workspace filters (spec 23 §19.3; AC-23.120).
 * Why: every filter change is a server call, so status and cluster must apply at once, search
 * only after 300 ms of quiet, and Clear filters must reset all three.
 * What: the component with fake timers and a change spy.
 * Must not: call an API (the page tests cover the refetch).
 */
import { act, fireEvent, render, screen } from '@testing-library/react'
import { SessionFilters } from './SessionFilters'
import { NO_FILTERS } from '../../utils/workspaceFormat'
import type { ReviewFilters } from '../../types/workspace'

const CLUSTERS = [
  { code: 'FIN', name: 'Finance', description: '' },
  { code: 'IT', name: 'IT & Security', description: '' },
]

function setup(value: ReviewFilters = NO_FILTERS, failed = false) {
  const onChange = vi.fn()
  render(<SessionFilters value={value} onChange={onChange} clusters={CLUSTERS} clustersFailed={failed} />)
  return onChange
}

afterEach(() => vi.useRealTimers())

it('status and cluster change at once; the cluster list reads "<code> · <name>" (AC-23.120)', () => {
  const onChange = setup()
  expect(screen.getByRole('region', { name: 'Session filters' })).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'finished' } })
  expect(onChange).toHaveBeenLastCalledWith({ ...NO_FILTERS, status: 'finished' })
  expect(screen.getByRole('option', { name: 'FIN · Finance' })).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Cluster'), { target: { value: 'IT' } })
  expect(onChange).toHaveBeenLastCalledWith({ ...NO_FILTERS, cluster: 'IT' })
  expect(screen.queryByRole('button', { name: 'Clear filters' })).toBeNull()
})

it('search sends the trimmed text once, 300 ms after the last key (AC-23.120)', () => {
  vi.useFakeTimers()
  const onChange = setup()
  const box = screen.getByRole('searchbox', { name: 'Search' })
  expect(box).toHaveAttribute('maxLength', '100')
  fireEvent.change(box, { target: { value: ' co' } })
  act(() => vi.advanceTimersByTime(200))
  fireEvent.change(box, { target: { value: ' cost ' } })
  act(() => vi.advanceTimersByTime(299))
  expect(onChange).not.toHaveBeenCalled()
  act(() => vi.advanceTimersByTime(1))
  expect(onChange).toHaveBeenCalledTimes(1)
  expect(onChange).toHaveBeenCalledWith({ ...NO_FILTERS, q: 'cost' })
})

it('Clear filters shows with a filter set and resets all three (AC-23.120)', () => {
  const onChange = setup({ status: 'active', cluster: 'FIN', q: 'cost' })
  fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
  expect(onChange).toHaveBeenCalledWith(NO_FILTERS)
  expect(screen.getByRole('searchbox', { name: 'Search' })).toHaveValue('')
})

it('without the taxonomy the cluster select only has All clusters and is disabled (AC-23.120)', () => {
  setup(NO_FILTERS, true)
  expect(screen.getByLabelText('Cluster')).toBeDisabled()
  expect(screen.getAllByRole('option').filter((o) => o.closest('select') === screen.getByLabelText('Cluster'))).toHaveLength(1)
})
