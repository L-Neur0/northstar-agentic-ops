/**
 * Tests for the one dialog primitive every modal uses (spec 23 §3.9; AC-23.46).
 * Why: one `Modal` owns the portal, focus
 * move-in, Tab cycle, Escape and backdrop close, focus return, and "only the top dialog reacts to
 * Escape" when two are mounted.
 * Rules: `dismissible={false}` ignores Escape and backdrop and hides the close button.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { Modal } from './Modal'

function Harness({ dismissible = true, nested = false }: { dismissible?: boolean; nested?: boolean }) {
  const [open, setOpen] = useState(false)
  const [inner, setInner] = useState(nested)
  return (
    <>
      <button onClick={() => setOpen(true)}>Open</button>
      {open && (
        <Modal title="Outer" onClose={() => setOpen(false)} dismissible={dismissible}>
          <button>First</button>
          <button>Last</button>
        </Modal>
      )}
      {open && inner && (
        <Modal title="Inner" onClose={() => setInner(false)}>
          <button>Inner action</button>
        </Modal>
      )}
    </>
  )
}

describe('Modal (AC-23.46)', () => {
  it('is a labelled modal dialog that moves focus in, cycles Tab and returns focus', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    const trigger = screen.getByRole('button', { name: 'Open' })
    await user.click(trigger)
    const dialog = screen.getByRole('dialog', { name: 'Outer' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(dialog).toContainElement(document.activeElement as HTMLElement)

    // Tab cycles inside: close (x), First, Last, back to close.
    const close = screen.getByRole('button', { name: 'Close dialog' })
    close.focus()
    await user.tab()
    expect(screen.getByRole('button', { name: 'First' })).toHaveFocus()
    await user.tab()
    expect(screen.getByRole('button', { name: 'Last' })).toHaveFocus()
    await user.tab()
    expect(close).toHaveFocus()
    await user.tab({ shift: true })
    expect(screen.getByRole('button', { name: 'Last' })).toHaveFocus()

    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it('closes on a backdrop click', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByRole('button', { name: 'Open' }))
    await user.click(screen.getByTestId('modal-backdrop'))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('ignores Escape and backdrop and has no close button when not dismissible', async () => {
    const user = userEvent.setup()
    render(<Harness dismissible={false} />)
    await user.click(screen.getByRole('button', { name: 'Open' }))
    await user.keyboard('{Escape}')
    await user.click(screen.getByTestId('modal-backdrop'))
    expect(screen.getByRole('dialog', { name: 'Outer' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Close dialog' })).not.toBeInTheDocument()
  })

  it('closes only the top dialog on one Escape', async () => {
    const user = userEvent.setup()
    render(<Harness nested />)
    await user.click(screen.getByRole('button', { name: 'Open' }))
    expect(screen.getAllByRole('dialog')).toHaveLength(2)
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog', { name: 'Inner' })).not.toBeInTheDocument()
    expect(screen.getByRole('dialog', { name: 'Outer' })).toBeInTheDocument()
  })
})
