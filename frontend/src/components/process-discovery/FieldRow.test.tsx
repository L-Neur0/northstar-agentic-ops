/**
 * Tests for the open-conflict marker on a field row (spec 23 §11.7, amended 2026-11-20; AC-23.146).
 * Why: when a document disagrees with a stored value, the expert must see on the panel which field
 * is under dispute and where to settle it, without the panel offering a way to settle it itself.
 * What: an open conflict shows "Conflict – answer in the chat" and adds no button; a left conflict
 * and no conflict show nothing. Rules: the marker is text, not colour alone. Must not: call the API.
 */
import { render, screen } from '@testing-library/react'
import { FieldRow } from './FieldRow'
import { view } from '../../test/fixtures/sessions'

const MARKER = 'Conflict – answer in the chat'

describe('FieldRow open-conflict marker (AC-23.146)', () => {
  it('marks a field with an open conflict and adds no button', () => {
    render(
      <ul>
        <FieldRow view={view('process.trigger', 'complete', { conflict: 'open' })} value="Month-end close" />
      </ul>,
    )
    expect(screen.getByText(MARKER)).toBeInTheDocument()
    expect(screen.getByText('Month-end close')).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it.each([['left' as const], [null]])('shows no marker for conflict %s', (conflict) => {
    render(
      <ul>
        <FieldRow view={view('process.trigger', 'complete', { conflict })} value="Month-end close" />
      </ul>,
    )
    expect(screen.queryByText(MARKER)).not.toBeInTheDocument()
  })
})
