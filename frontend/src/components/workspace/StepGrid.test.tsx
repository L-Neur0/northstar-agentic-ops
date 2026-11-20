/**
 * Tests for the workspace step grid (spec 23 §19.4 block 2; AC-23.125, AC-23.126).
 * Why: the grid is how the specialist reads the steps; the toggle must switch to the expert's first
 * version only when the server kept one, and cells must be plain, safe text with source and status.
 * What: the component with the fixture grids.
 * Must not: format values (the server sends display text, Q15).
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { StepGrid } from './StepGrid'
import { rawStepGrid, stepGrid } from '../../test/fixtures/workspace'

describe('version toggle (AC-23.125)', () => {
  it('shows Now by default and switches to the first version and back', async () => {
    render(<StepGrid steps={stepGrid} rawSteps={rawStepGrid} />)
    const now = screen.getByRole('button', { name: 'Now' })
    const first = screen.getByRole('button', { name: 'As first told' })
    expect(screen.getByRole('group', { name: 'Step version' })).toBeInTheDocument()
    expect(now).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('table', { name: 'Steps now, one column per step' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Step 2 · Consolidate' })).toBeInTheDocument()
    await userEvent.click(first)
    expect(first).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('table', { name: 'Steps as the expert first told them, one column per step' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Step 2 · Merge the files' })).toBeInTheDocument()
    await userEvent.click(now)
    expect(screen.getByRole('columnheader', { name: 'Step 2 · Consolidate' })).toBeInTheDocument()
  })

  it('without a first version the toggle is disabled and the reason is visible', () => {
    render(<StepGrid steps={stepGrid} rawSteps={null} />)
    const first = screen.getByRole('button', { name: 'As first told' })
    expect(first).toBeDisabled()
    expect(first).toHaveAccessibleDescription("The expert's first version was not kept, because nothing changed it.")
  })
})

describe('cells (AC-23.126)', () => {
  it('shows the value, the source word and the status word; markup stays text; no inputs', () => {
    const { container } = render(<StepGrid steps={stepGrid} rawSteps={null} />)
    const region = screen.getByRole('region', { name: 'Step grid' })
    expect(region).toHaveAttribute('tabindex', '0')
    const rows = within(region).getAllByRole('row')
    expect(within(rows[1]).getByRole('rowheader')).toHaveTextContent('Step name')
    const cells = within(rows[1]).getAllByRole('cell')
    expect(cells[0]).toHaveTextContent('Collect cost data')
    expect(cells[0]).toHaveTextContent('expert · Complete')
    expect(cells[1]).toHaveTextContent('from a document · Proposed')
    const systems = within(rows[2]).getAllByRole('cell')
    expect(systems[1]).toHaveTextContent('<img src=x onerror=alert(1)>')
    expect(systems[1]).toHaveTextContent('Partly answered')
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('input, textarea, select')).toBeNull()
  })

  it('a session without steps says so', () => {
    render(<StepGrid steps={{ stepNames: [], rows: [] }} rawSteps={null} />)
    expect(screen.getByText('No steps yet.')).toBeInTheDocument()
    expect(screen.queryByRole('table')).toBeNull()
  })
})
