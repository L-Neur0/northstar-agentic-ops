/**
 * Tests for the read-only session popup (spec 23 §19.4, §19.7; AC-23.122–23.124, AC-23.128–23.130,
 * AC-23.133–23.137).
 * Why: the popup is where the specialist reads one session, downloads its PDF and may delete it;
 * it must load once, survive a broken report part, never edit, and handle delete conflicts.
 * What: the popup against the fake API (seed sessions, stored specialist token) with a stub map
 * renderer and a stubbed `saveBlob`; some calls are spied or replaced to shape a failure.
 * Must not: run Mermaid or start a real download.
 */
import { StrictMode, createElement } from 'react'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SessionDialog } from './SessionDialog'
import { renderWithProviders } from '../../test/render'
import { reviewRow, stubMap, workspaceFake } from '../../test/fixtures/workspace'
import { withFailedNote } from '../../test/fixtures/report'
import { ApiError, type DiscoveryApi } from '../../services/api'
import * as download from '../../utils/downloadFile'
import type { ReviewRow } from '../../types/workspace'

// The opportunity list can be made to throw while rendering, to prove its boundary (AC-23.130).
const boom = vi.hoisted(() => ({ on: false }))
vi.mock('../report/ReportParts', async (load) => {
  const real = await load<typeof import('../report/ReportParts')>()
  return {
    ...real,
    OpportunityList: (props: Parameters<typeof real.OpportunityList>[0]) => {
      if (boom.on) throw new TypeError('bad part')
      return createElement(real.OpportunityList, props)
    },
  }
})

const FINISHED = reviewRow({ id: 'seed-cost-review', processName: 'Monthly cost review' })
const ACTIVE = reviewRow({ id: 'seed-onboarding', processName: 'Laptop onboarding', status: 'active', phase: 'steps' })

function open(row: ReviewRow = FINISHED, api: DiscoveryApi = workspaceFake(), strict = false, canDelete?: boolean) {
  const props = { onClose: vi.fn(), onDeleted: vi.fn(), onSessionEnded: vi.fn() }
  const ui = <SessionDialog row={row} mapRenderer={stubMap} canDelete={canDelete} {...props} />
  renderWithProviders(strict ? <StrictMode>{ui}</StrictMode> : ui, { api })
  return { ...props, api, user: userEvent.setup() }
}

afterEach(() => {
  boom.on = false
  vi.restoreAllMocks()
  sessionStorage.clear()
})

describe('popup frame (AC-23.122, AC-23.123)', () => {
  it('is a dialog named by the process, with the session line and the two tabs', async () => {
    const { user, onClose } = open()
    const dialog = screen.getByRole('dialog', { name: 'Monthly cost review' })
    expect(dialog).toHaveAccessibleDescription(/^Session seed-cost-review · Updated 2 hours ago$/)
    expect(await screen.findByRole('tab', { name: 'Session' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: 'Conversation' })).toHaveAttribute('aria-selected', 'false')
    await user.click(screen.getByRole('button', { name: 'Close' }))
    await user.click(screen.getByRole('button', { name: 'Close dialog' }))
    await user.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledTimes(3)
  })

  it('names an unnamed session "Not named yet"', () => {
    open(reviewRow({ id: 'seed-unnamed', processName: null, status: 'active', phase: 'context' }))
    expect(screen.getByRole('dialog', { name: 'Not named yet' })).toBeInTheDocument()
  })

  it('calls the view once under StrictMode and shows the loading status', async () => {
    const api = workspaceFake()
    const spy = vi.spyOn(api, 'reviewSession')
    open(FINISHED, api, true)
    expect(screen.getByRole('status')).toHaveTextContent('Loading the session…')
    await screen.findByRole('tab', { name: 'Session' })
    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('a 404 says the session no longer exists and closing asks for a list refresh', async () => {
    const { user, onClose } = open(reviewRow({ id: 'gone' }))
    expect(await screen.findByText('This session no longer exists.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledWith(true)
  })

  it('other errors show the sentence and Retry', async () => {
    const api = workspaceFake()
    vi.spyOn(api, 'reviewSession').mockRejectedValueOnce(new ApiError(503, 'store_unavailable', 'Down.'))
    const { user } = open(FINISHED, api)
    expect(await screen.findByRole('alert')).toHaveTextContent('Down.')
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('tab', { name: 'Session' })).toBeInTheDocument()
  })

  it('a 401 on the view is handed to the page', async () => {
    const api = workspaceFake()
    vi.spyOn(api, 'reviewSession').mockRejectedValueOnce(new ApiError(401, 'workspace_code_required', ''))
    const { onSessionEnded } = open(FINISHED, api)
    await waitFor(() => expect(onSessionEnded).toHaveBeenCalled())
  })
})

describe('session tab (AC-23.124, AC-23.128, AC-23.129)', () => {
  it('shows the four cards with their values', async () => {
    open()
    await screen.findByRole('tab', { name: 'Session' })
    for (const title of ['Context', 'Process', 'Scope', 'Measures']) {
      const card = screen.getByRole('region', { name: title })
      expect(within(card).getByRole('heading', { level: 3, name: title })).toBeInTheDocument()
    }
    const context = screen.getByRole('region', { name: 'Context' })
    expect(within(context).getByText('Finance control')).toBeInTheDocument()
    const measures = screen.getByRole('region', { name: 'Measures' })
    expect(within(measures).getByText(/^\d+ %$/)).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'Process' })).getByText('Mapped')).toBeInTheDocument()
  })

  it('lists documents with kind, date and outcome, never size', async () => {
    open()
    await screen.findByRole('tab', { name: 'Session' })
    const docs = screen.getByRole('region', { name: 'Documents' })
    expect(docs).toHaveTextContent(/cost-review-procedure\.pdf · PDF · \d+ \w{3} \d{4} · read/)
    expect(docs).toHaveTextContent(/old-template\.xlsx · Excel · .* · could not be read/)
    expect(docs).not.toHaveTextContent(/18432|18,432|KB/)
  })

  it('renders the step assessment, route, opportunities and map with h3 part headings', async () => {
    open()
    await screen.findByRole('tab', { name: 'Session' })
    expect(screen.getByRole('heading', { level: 3, name: 'Step-by-step AI assessment' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 3, name: 'Recommended route' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 3, name: 'Process map' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Step-by-step assessment' })).toBeInTheDocument()
    expect(await screen.findByRole('img', { name: /^Process map:/ })).toBeInTheDocument()
    expect(screen.queryAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual(['Monthly cost review'])
  })

  it('an active session shows the ready-once-finished note instead, and no documents block', async () => {
    open(ACTIVE)
    expect(await screen.findByText('The assessment and the map are ready once the expert finishes the interview.')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Step-by-step AI assessment' })).toBeNull()
    expect(screen.queryByRole('region', { name: 'Documents' })).toBeNull()
  })
})

describe('report blocks that fail (AC-23.130)', () => {
  it('a failed note shows the warning; a part that throws shows "This part could not be shown." and the rest renders', async () => {
    const api = workspaceFake()
    const real = api.reviewSession.bind(api)
    vi.spyOn(api, 'reviewSession').mockImplementation(async (id) => {
      const view = await real(id)
      const report = withFailedNote(view.report!, ['steps'])
      return { ...view, report }
    })
    vi.spyOn(console, 'error').mockImplementation(() => {})
    boom.on = true
    open(FINISHED, api)
    await screen.findByRole('tab', { name: 'Session' })
    expect(document.querySelector('[data-note-kind="failed"]')).not.toBeNull()
    expect(screen.getByText('This part could not be shown.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 3, name: 'Recommended route' })).toBeInTheDocument()
  })
})

describe('PDF (AC-23.133)', () => {
  it('is disabled with the visible reason before finish', async () => {
    open(ACTIVE)
    const button = await screen.findByRole('button', { name: 'Download report (PDF)' })
    expect(button).toBeDisabled()
    expect(button).toHaveAccessibleDescription('The report is ready once the interview is finished.')
  })

  it('downloads once with "Preparing PDF…" and saves under the returned name', async () => {
    const save = vi.spyOn(download, 'saveBlob').mockImplementation(() => {})
    const api = workspaceFake()
    let finish!: (v: { blob: Blob; filename: string }) => void
    const spy = vi.spyOn(api, 'getReviewReportPdf').mockImplementation(() => new Promise((r) => (finish = r)))
    const { user } = open(FINISHED, api)
    await user.click(await screen.findByRole('button', { name: 'Download report (PDF)' }))
    expect(screen.getByRole('button', { name: /Preparing PDF…/ })).toBeDisabled()
    finish({ blob: new Blob(['%PDF']), filename: 'x.pdf' })
    await waitFor(() => expect(save).toHaveBeenCalledWith(expect.any(Blob), 'x.pdf'))
    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('a 409 shows the not-ready sentence inline and keeps the popup', async () => {
    const api = workspaceFake()
    vi.spyOn(api, 'getReviewReportPdf').mockRejectedValue(new ApiError(409, 'report_not_ready', 'x'))
    const { user } = open(FINISHED, api)
    await user.click(await screen.findByRole('button', { name: 'Download report (PDF)' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The report is ready once the interview is finished.')
    expect(screen.getByRole('dialog', { name: 'Monthly cost review' })).toBeInTheDocument()
  })
})

describe('delete (AC-23.134–23.137)', () => {
  it('opens an alertdialog with Cancel focused; Cancel makes no call; one Escape closes only the confirm', async () => {
    const api = workspaceFake()
    const spy = vi.spyOn(api, 'deleteReviewSession')
    const { user, onClose } = open(FINISHED, api)
    await user.click(await screen.findByRole('button', { name: 'Delete session' }))
    const confirm = screen.getByRole('alertdialog', { name: 'Delete this session?' })
    expect(confirm).toHaveTextContent(
      "This removes the session, its map and its report for everyone, including the expert. The expert's ideas stay. This cannot be undone.",
    )
    expect(within(confirm).getByRole('button', { name: 'Cancel' })).toHaveFocus()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(onClose).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Delete session' }))
    await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Cancel' }))
    expect(spy).not.toHaveBeenCalled()
  })

  it('confirming sends the loaded etag and reports "Session deleted."', async () => {
    const api = workspaceFake()
    const spy = vi.spyOn(api, 'deleteReviewSession')
    const etag = (await api.reviewSession('seed-cost-review')).etag
    const { user, onDeleted } = open(FINISHED, api)
    await user.click(await screen.findByRole('button', { name: 'Delete session' }))
    await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Delete session' }))
    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith('Session deleted.'))
    expect(spy).toHaveBeenCalledWith('seed-cost-review', etag)
  })

  it('a 409 closes the confirm, reloads the view, shows the conflict sentence; the next delete sends the new etag', async () => {
    const api = workspaceFake()
    const spy = vi.spyOn(api, 'deleteReviewSession')
    const { user, onDeleted } = open(FINISHED, api)
    await screen.findByRole('tab', { name: 'Session' })
    await api.reviewList({ status: null, cluster: null, q: '/touch seed-cost-review' })
    await user.click(screen.getByRole('button', { name: 'Delete session' }))
    await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Delete session' }))
    expect(await screen.findByText(/This session changed while you were looking/)).toBeInTheDocument()
    expect(screen.queryByRole('alertdialog')).toBeNull()
    const first = spy.mock.calls[0][1]
    await user.click(screen.getByRole('button', { name: 'Delete session' }))
    await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Delete session' }))
    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith('Session deleted.'))
    expect(spy.mock.calls[1][1]).not.toBe(first)
  })

  it('a 404 reports "This session was already deleted."', async () => {
    const api = workspaceFake()
    vi.spyOn(api, 'deleteReviewSession').mockRejectedValue(new ApiError(404, 'not_found', 'Not found.'))
    const { user, onDeleted } = open(FINISHED, api)
    await user.click(await screen.findByRole('button', { name: 'Delete session' }))
    await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Delete session' }))
    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith('This session was already deleted.'))
  })

  it('while in flight the buttons are disabled, "Deleting…" shows and Escape is ignored', async () => {
    const api = workspaceFake()
    vi.spyOn(api, 'deleteReviewSession').mockImplementation(() => new Promise(() => {}))
    const { user, onClose } = open(FINISHED, api)
    await user.click(await screen.findByRole('button', { name: 'Delete session' }))
    const confirm = screen.getByRole('alertdialog')
    await user.click(within(confirm).getByRole('button', { name: 'Delete session' }))
    expect(within(confirm).getByText('Deleting…')).toBeInTheDocument()
    expect(within(confirm).getByRole('button', { name: 'Cancel' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Close' })).toBeDisabled()
    await user.keyboard('{Escape}')
    expect(screen.getByRole('alertdialog')).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
  })
})

describe('open workspace (AC-23.144, amended 2026-11-20)', () => {
  it('renders no Delete session button when delete is switched off; Download and Close stay', async () => {
    open(FINISHED, workspaceFake(), false, false)
    expect(await screen.findByRole('button', { name: 'Download report (PDF)' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Delete session' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Close' })).toBeInTheDocument()
  })

  it('renders Delete session when delete is allowed', async () => {
    open(FINISHED, workspaceFake(), false, true)
    expect(await screen.findByRole('button', { name: 'Delete session' })).toBeInTheDocument()
  })
})
