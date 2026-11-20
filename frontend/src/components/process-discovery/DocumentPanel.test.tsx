/**
 * Tests for the Documents section (spec 23 §11.2–§11.6; AC-23.61, AC-23.64, AC-23.65, AC-23.67,
 * AC-23.70, AC-23.71, AC-23.74).
 * Why: the panel is where the expert sees what was read from a file and removes it; its words,
 * counts and confirmations must match the spec exactly, and nothing about the file's content may
 * show.
 * What: the panel rendered with props (the page wiring is covered by the page tests).
 * Must not: call an API; callbacks are spies.
 */
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DocumentPanel } from './DocumentPanel'
import type { DocumentOut } from '../../types/process-discovery'

const limits = { allowedTypes: ['pdf', 'docx', 'xlsx', 'csv', 'txt', 'md', 'bpmn', 'xml'], maxFiles: 5, maxFileMb: 10, maxImageMb: 5 }

const doc = (over: Partial<DocumentOut>): DocumentOut => ({
  id: 'd1',
  name: 'cost-review.docx',
  kind: 'docx',
  bytes: 38347,
  chars: 987,
  truncated: false,
  uploadedAt: '2026-11-19T10:00:00Z',
  outcome: 'read',
  proposals: 6,
  pending: 4,
  ...over,
})

function renderPanel(over: Partial<Parameters<typeof DocumentPanel>[0]> = {}) {
  const props = {
    documents: [] as DocumentOut[],
    editable: true,
    busy: false,
    limits,
    uploading: null,
    removingId: null,
    notice: null,
    error: null,
    collapsed: false,
    onToggle: vi.fn(),
    onOpenPicker: vi.fn(),
    onFile: vi.fn(),
    onRemove: vi.fn(),
    onDismissNotice: vi.fn(),
    onDismissError: vi.fn(),
    ...over,
  }
  render(<DocumentPanel {...props} />)
  return props
}

describe('header, button and helper line (AC-23.61)', () => {
  it('shows Documents n/max, the button and the helper line from the config', () => {
    renderPanel({ documents: [doc({})] })
    expect(screen.getByRole('button', { name: /^Documents/ })).toHaveTextContent('1/5')
    expect(screen.getByRole('button', { name: /Add a document/ })).toBeInTheDocument()
    expect(screen.getByText('PDF, Word, Excel, CSV, text, Markdown or BPMN · up to 10 MB · up to 5 files')).toBeInTheDocument()
  })

  it('without the config it still offers the button and shows no helper line', async () => {
    const p = renderPanel({ limits: null })
    await userEvent.click(screen.getByRole('button', { name: /Add a document/ }))
    expect(p.onOpenPicker).toHaveBeenCalled()
    expect(screen.queryByText(/up to 10 MB/)).not.toBeInTheDocument()
  })

  it('says "No documents yet." when the list is empty', () => {
    renderPanel()
    expect(screen.getByText('No documents yet.')).toBeInTheDocument()
  })
})

describe('drop (AC-23.64)', () => {
  it('two dropped files: the first is uploaded and the panel says so', () => {
    const p = renderPanel()
    const files = [new File(['x'], 'first.docx'), new File(['y'], 'second.pdf')]
    fireEvent.drop(screen.getByRole('button', { name: /Add a document/ }), { dataTransfer: { types: ['Files'], files } })
    expect(p.onFile).toHaveBeenCalledWith(files[0])
    expect(screen.getByText('One file at a time: I took first.docx.')).toBeInTheDocument()
  })
})

describe('progress (AC-23.65)', () => {
  it('shows a labelled progressbar while sending, then a reading status', () => {
    renderPanel({ uploading: { name: 'cost-review.docx', percent: 62, stage: 'sending' } })
    expect(screen.getByText('Uploading cost-review.docx')).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: 'Upload progress' })).toHaveAttribute('aria-valuenow', '62')
  })

  it('reading stage is a status with the file name', () => {
    renderPanel({ uploading: { name: 'cost-review.docx', percent: null, stage: 'reading' } })
    expect(screen.getByRole('status')).toHaveTextContent('Reading cost-review.docx…')
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  })
})

describe('result and error (AC-23.67, AC-23.68)', () => {
  it('shows the result as a dismissible status and an error as an alert', async () => {
    const p = renderPanel({ notice: 'I read "x.docx" and found 2 values.', error: 'This file is larger than 10 MB.' })
    expect(screen.getByRole('status')).toHaveTextContent('I read "x.docx" and found 2 values.')
    expect(screen.getByRole('alert')).toHaveTextContent('This file is larger than 10 MB.')
    const [dismissNotice, dismissError] = screen.getAllByRole('button', { name: 'Dismiss' })
    await userEvent.click(dismissNotice)
    await userEvent.click(dismissError)
    expect(p.onDismissNotice).toHaveBeenCalled()
    expect(p.onDismissError).toHaveBeenCalled()
  })
})

describe('the list (AC-23.70)', () => {
  it('shows name, kind word, read in part and the count text; never bytes or characters', () => {
    renderPanel({
      documents: [
        doc({ id: 'a' }),
        doc({ id: 'b', name: 'old-map.bpmn', kind: 'bpmn', truncated: true, proposals: 5, pending: 0 }),
        doc({ id: 'c', name: 'scan.pdf', kind: 'pdf', outcome: 'failed', proposals: 0, pending: 0 }),
        doc({ id: 'd', name: 'notes.txt', kind: 'txt', proposals: 0, pending: 0 }),
        doc({ id: 'e', name: 'one.md', kind: 'md', proposals: 1, pending: 1 }),
      ],
    })
    const list = screen.getByRole('list', { name: 'Your documents' })
    const items = within(list).getAllByRole('listitem')
    expect(items[0]).toHaveTextContent('Word · 6 proposals · 4 waiting for you')
    expect(items[1]).toHaveTextContent('BPMN · read in part · 5 proposals · all settled')
    expect(items[2]).toHaveTextContent('PDF · could not be read')
    expect(items[3]).toHaveTextContent('text · nothing new for the form')
    expect(items[4]).toHaveTextContent('Markdown · 1 proposal · 1 waiting for you')
    expect(list).not.toHaveTextContent('38347')
    expect(list).not.toHaveTextContent('987')
    expect(within(items[0]).getByText('cost-review.docx')).toHaveAttribute('title', 'cost-review.docx')
  })
})

describe('remove (AC-23.71)', () => {
  it('opens an alertdialog naming the pending proposals, Cancel focused first and making no call', async () => {
    const p = renderPanel({ documents: [doc({})] })
    await userEvent.click(screen.getByRole('button', { name: 'Remove cost-review.docx' }))
    const dialog = screen.getByRole('alertdialog', { name: 'Remove this document?' })
    expect(dialog).toHaveTextContent('Values you already confirmed from it stay. Its 4 unconfirmed proposals are removed.')
    expect(within(dialog).getByRole('button', { name: 'Cancel' })).toHaveFocus()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(p.onRemove).not.toHaveBeenCalled()
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })

  it('leaves out the second sentence without pending proposals; Remove calls back with the id', async () => {
    const p = renderPanel({ documents: [doc({ pending: 0 })] })
    await userEvent.click(screen.getByRole('button', { name: 'Remove cost-review.docx' }))
    const dialog = screen.getByRole('alertdialog')
    expect(dialog).not.toHaveTextContent('unconfirmed')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Remove' }))
    expect(p.onRemove).toHaveBeenCalledWith('d1')
  })

  it('shows "Removing…" on the row in flight', () => {
    renderPanel({ documents: [doc({})], removingId: 'd1' })
    expect(screen.getByText('Removing…')).toBeInTheDocument()
  })
})

describe('closed sessions (AC-23.74)', () => {
  it('hides the drop zone and Remove but keeps the list', () => {
    renderPanel({ documents: [doc({})], editable: false })
    expect(screen.queryByRole('button', { name: /Add a document/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Remove/ })).not.toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Your documents' })).toHaveTextContent('cost-review.docx')
  })
})
