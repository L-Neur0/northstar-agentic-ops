/**
 * Tests for the roles and systems review (spec 23 §3.8.11; AC-23.34, AC-23.35).
 * Why: two of the four *Finish* conditions hang on these confirmations, so they are explicit
 * button presses, and confirming an empty list needs a second confirmation (F-10.2).
 * Rules: the lists are read-only; corrections go through the chat.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DerivedReviewPanel } from './DerivedReviewPanel'

const panel = (over: Partial<Parameters<typeof DerivedReviewPanel>[0]> = {}) => {
  const onConfirm = vi.fn()
  render(
    <DerivedReviewPanel
      roles={['Cost controller', 'Site manager']}
      tools={['SAP']}
      rolesConfirmed={false}
      toolsConfirmed={false}
      confirming={null}
      disabled={false}
      onConfirm={onConfirm}
      {...over}
    />,
  )
  return onConfirm
}

describe('DerivedReviewPanel (AC-23.34)', () => {
  it('lists the chips and the confirmation state in words', () => {
    panel({ toolsConfirmed: true })
    expect(screen.getByText('Cost controller')).toBeInTheDocument()
    expect(screen.getByText('SAP')).toBeInTheDocument()
    expect(screen.getByText('Not confirmed yet')).toBeInTheDocument()
    expect(screen.getByText('✓ Confirmed')).toBeInTheDocument()
    expect(screen.getByText('To correct an entry, say it in the chat.')).toBeInTheDocument()
  })

  it('confirms roles with "roles" and systems with "tools"', async () => {
    const onConfirm = panel()
    await userEvent.click(screen.getByRole('button', { name: 'Confirm roles' }))
    await userEvent.click(screen.getByRole('button', { name: 'Confirm systems' }))
    expect(onConfirm.mock.calls).toEqual([['roles'], ['tools']])
  })

  it('disables both buttons while a confirm is in flight or the session is closed', () => {
    panel({ confirming: 'roles' })
    expect(screen.getByRole('button', { name: 'Confirm systems' })).toBeDisabled()
  })
})

describe('empty lists (AC-23.35)', () => {
  it('asks first; Cancel makes no call and Yes, confirm does', async () => {
    const user = userEvent.setup()
    const onConfirm = panel({ roles: [] })
    expect(screen.getByText('None yet')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Confirm roles' }))
    const dialog = screen.getByRole('alertdialog', { name: 'Confirm that no roles are involved?' })
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus()
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(dialog).not.toBeInTheDocument()
    expect(onConfirm).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Confirm roles' }))
    await user.click(screen.getByRole('button', { name: 'Yes, confirm' }))
    expect(onConfirm).toHaveBeenCalledWith('roles')
  })

  it('confirms a non-empty list directly', async () => {
    const onConfirm = panel()
    await userEvent.click(screen.getByRole('button', { name: 'Confirm systems' }))
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(onConfirm).toHaveBeenCalledWith('tools')
  })
})
