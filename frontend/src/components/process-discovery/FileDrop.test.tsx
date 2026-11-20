/**
 * Tests for the "Add a document" drop zone (spec 23 §11.4.1; AC-23.64).
 * Why: the zone must work by mouse, keyboard and drag-and-drop, and a drop of several files must
 * hand over all of them so the panel can take the first and say so.
 * What: click, Enter and Space open the picker; a drop hands the files over; the drag-over border.
 * Must not: read file content or call an API.
 */
import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FileDrop } from './FileDrop'

const files = (...names: string[]) => names.map((n) => new File(['x'], n))

it('opens the picker by click, Enter and Space (AC-23.64)', async () => {
  const onOpen = vi.fn()
  render(<FileDrop onOpen={onOpen} onFiles={vi.fn()} disabled={false} />)
  const button = screen.getByRole('button', { name: /Add a document/ })
  await userEvent.click(button)
  button.focus()
  await userEvent.keyboard('{Enter}')
  await userEvent.keyboard(' ')
  expect(onOpen).toHaveBeenCalledTimes(3)
})

it('a drop hands over the files and the zone shows a dashed primary border while dragging (AC-23.64)', () => {
  const onFiles = vi.fn()
  render(<FileDrop onOpen={vi.fn()} onFiles={onFiles} disabled={false} />)
  const zone = screen.getByRole('button', { name: /Add a document/ })
  const dropped = files('a.docx', 'b.pdf')
  fireEvent.dragOver(zone, { dataTransfer: { types: ['Files'], files: dropped } })
  expect(zone.className).toContain('border-primary')
  fireEvent.drop(zone, { dataTransfer: { types: ['Files'], files: dropped } })
  expect(onFiles).toHaveBeenCalledWith(dropped)
  expect(zone.className).not.toContain('bg-primary-soft')
})

it('does nothing while disabled', () => {
  const onFiles = vi.fn()
  render(<FileDrop onOpen={vi.fn()} onFiles={onFiles} disabled />)
  fireEvent.drop(screen.getByRole('button', { name: /Add a document/ }), { dataTransfer: { types: ['Files'], files: files('a.docx') } })
  expect(onFiles).not.toHaveBeenCalled()
})
