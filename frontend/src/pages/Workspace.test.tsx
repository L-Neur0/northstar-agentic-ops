/**
 * Page tests for the workspace (spec 23 §19.1–§19.3, §19.7; AC-23.106, AC-23.108, AC-23.113–23.115,
 * AC-23.120, AC-23.135, AC-23.140, AC-23.142; AC-23.143, AC-23.144 on the page, amended 2026-11-20
 * (open workspace)).
 * Why: the page ties login, list, popup and delete together; it must keep a valid token, return to
 * login whenever the server ends the session, never show an error as an empty list, and refresh the
 * list after a delete.
 * What: the page against the fake API with the five seed sessions (no delay, no storage of the
 * fake) and a stub map renderer; the token lives in jsdom's sessionStorage.
 * Must not: run Mermaid or call a real server.
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Workspace } from './Workspace'
import { renderWithProviders } from '../test/render'
import { createFakeApi } from '../services/fakeApi'
import { ApiError } from '../services/api'
import { specialistLogin, stubMap } from '../test/fixtures/workspace'
import { readWorkspaceToken, storeWorkspaceToken, WORKSPACE_TOKEN_KEY } from '../access/workspaceToken'
import { VISITOR_KEY_STORAGE } from '../access/visitorKey'

const fake = () => createFakeApi({ delayMs: 0, persist: false, workspaceSeed: true })

function open(api = fake()) {
  renderWithProviders(<Workspace mapRenderer={stubMap} />, { api, route: '/workspace' })
  return { api, user: userEvent.setup() }
}

afterEach(() => {
  vi.restoreAllMocks()
  sessionStorage.clear()
  localStorage.clear()
})

describe('token on load (AC-23.106)', () => {
  it('no token shows the login', () => {
    open()
    expect(screen.getByRole('heading', { name: 'Workspace' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'AI Use Case Discovery Agent · Workspace' })).toBeInTheDocument()
  })

  it('a valid stored token shows the list without asking again', async () => {
    storeWorkspaceToken(specialistLogin())
    open()
    expect(await screen.findByRole('table')).toBeInTheDocument()
  })

  it('an expired token is removed and the login shows', () => {
    sessionStorage.setItem(WORKSPACE_TOKEN_KEY, JSON.stringify({ ...specialistLogin(), expiresAt: '2000-01-01T00:00:00Z' }))
    open()
    expect(screen.getByRole('button', { name: 'Open workspace' })).toBeInTheDocument()
    expect(sessionStorage.getItem(WORKSPACE_TOKEN_KEY)).toBeNull()
  })
})

describe('login to list (AC-23.108, AC-23.114, AC-23.115)', () => {
  it('logs in, shows the header actions, then Log out returns to login and keeps the visitor key', async () => {
    localStorage.setItem(VISITOR_KEY_STORAGE, 'Visitorkeyvisitorkey12')
    const { user } = open()
    await user.type(screen.getByLabelText('Access code'), 'demo-specialist')
    await user.type(screen.getByLabelText('Your name'), 'Maria')
    await user.click(screen.getByRole('button', { name: 'Open workspace' }))
    expect(await screen.findByRole('table')).toBeInTheDocument()
    expect(screen.getByText('Signed in as Maria')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Refresh' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Switch to (dark|light) theme/ })).toBeInTheDocument()
    expect(screen.getByText(/5 sessions · 2 in progress · 2 mapped · 1 ended with nothing to map/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Log out' }))
    expect(screen.getByRole('button', { name: 'Open workspace' })).toBeInTheDocument()
    expect(readWorkspaceToken()).toBeNull()
    expect(localStorage.getItem(VISITOR_KEY_STORAGE)).toBe('Visitorkeyvisitorkey12')
  })

  it('shows "Loading sessions…" while the list loads, and a failed list as an alert with Retry, never zero counts', async () => {
    storeWorkspaceToken(specialistLogin())
    const api = fake()
    const real = api.reviewList.bind(api)
    vi.spyOn(api, 'reviewList').mockRejectedValueOnce(new ApiError(503, 'store_unavailable', 'The store is down.')).mockImplementation(real)
    const { user } = open(api)
    expect(screen.getByRole('status')).toHaveTextContent('Loading sessions…')
    expect(await screen.findByRole('alert')).toHaveTextContent('The store is down.')
    expect(screen.queryByRole('table')).toBeNull()
    expect(screen.queryByText(/0 sessions/)).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('table')).toBeInTheDocument()
  })

  it('a status filter refetches with status= and the counts add the match part (AC-23.120)', async () => {
    storeWorkspaceToken(specialistLogin())
    const api = fake()
    const spy = vi.spyOn(api, 'reviewList')
    const { user } = open(api)
    await screen.findByRole('table')
    await user.selectOptions(screen.getByLabelText('Status'), 'finished')
    await waitFor(() => expect(spy).toHaveBeenLastCalledWith({ status: 'finished', cluster: null, q: '' }))
    expect(await screen.findByText(/2 match the filters/)).toBeInTheDocument()
  })
})

describe('session ended (AC-23.113, AC-23.140)', () => {
  it.each([
    ['list', 401, 'workspace_code_required', 'Your workspace session has ended. Enter the access code again.'],
    ['list', 403, 'forbidden', 'This access code does not open the workspace.'],
  ])('a %s %s clears the token and shows the login with its sentence', async (_call, status, code, sentence) => {
    storeWorkspaceToken(specialistLogin())
    const api = fake()
    vi.spyOn(api, 'reviewList').mockRejectedValue(new ApiError(status, code, ''))
    open(api)
    expect(await screen.findByText(sentence)).toBeInTheDocument()
    expect(readWorkspaceToken()).toBeNull()
  })

  it.each<[string, (a: ReturnType<typeof fake>) => void, (u: ReturnType<typeof userEvent.setup>) => Promise<void>]>([
    ['view', (a) => vi.spyOn(a, 'reviewSession').mockRejectedValue(new ApiError(401, 'workspace_code_required', '')), async () => {}],
    [
      'conversation',
      (a) => vi.spyOn(a, 'reviewConversation').mockRejectedValue(new ApiError(403, 'forbidden', '')),
      async (u) => u.click(await screen.findByRole('tab', { name: 'Conversation' })),
    ],
    [
      'PDF',
      (a) => vi.spyOn(a, 'getReviewReportPdf').mockRejectedValue(new ApiError(401, 'workspace_code_required', '')),
      async (u) => u.click(await screen.findByRole('button', { name: 'Download report (PDF)' })),
    ],
    [
      'delete',
      (a) => vi.spyOn(a, 'deleteReviewSession').mockRejectedValue(new ApiError(401, 'workspace_code_required', '')),
      async (u) => {
        await u.click(await screen.findByRole('button', { name: 'Delete session' }))
        await u.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Delete session' }))
      },
    ],
  ])('a session-ending error on the %s closes the popup and shows the login', async (_name, arrange, act) => {
    storeWorkspaceToken(specialistLogin())
    const api = fake()
    arrange(api)
    const { user } = open(api)
    await user.click(await screen.findByRole('button', { name: 'Open session Monthly cost review' }))
    await act(user)
    expect(await screen.findByRole('button', { name: 'Open workspace' })).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(readWorkspaceToken()).toBeNull()
  })

  it('/expire typed in Search ends the session on the next call', async () => {
    storeWorkspaceToken(specialistLogin())
    const api = fake()
    const spy = vi.spyOn(api, 'reviewList')
    const { user } = open(api)
    await screen.findByRole('table')
    await user.type(screen.getByRole('searchbox', { name: 'Search' }), '/expire')
    await waitFor(() => expect(spy).toHaveBeenLastCalledWith({ status: null, cluster: null, q: '/expire' }))
    await user.click(await screen.findByRole('button', { name: 'Open session Monthly cost review' }))
    expect(await screen.findByText('Your workspace session has ended. Enter the access code again.')).toBeInTheDocument()
  })
})

describe('open and delete (AC-23.121, AC-23.135)', () => {
  it('closing the popup returns focus to the row button', async () => {
    storeWorkspaceToken(specialistLogin())
    const { user } = open()
    const button = await screen.findByRole('button', { name: 'Open session Monthly cost review' })
    await user.click(button)
    await user.click(await screen.findByRole('button', { name: 'Close' }))
    expect(button).toHaveFocus()
  })

  it('a delete closes both dialogs, refetches the list without the row and says "Session deleted."', async () => {
    storeWorkspaceToken(specialistLogin())
    const { user } = open()
    await user.click(await screen.findByRole('button', { name: 'Open session Supplier invoice check' }))
    await user.click(await screen.findByRole('button', { name: 'Delete session' }))
    await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Delete session' }))
    expect(await screen.findByText('Session deleted.')).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).toBeNull()
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Open session Supplier invoice check' })).toBeNull())
    expect(screen.getByText(/4 sessions/)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('region', { name: 'Session list' })).toHaveFocus())
  })
})

describe('small screens (AC-23.142)', () => {
  it('header actions have aria-labels and the list scrolls inside its region', async () => {
    storeWorkspaceToken(specialistLogin())
    open()
    const region = await screen.findByRole('region', { name: 'Session list' })
    expect(region.className).toContain('overflow-x-auto')
    expect(screen.getByRole('button', { name: 'Refresh' })).toHaveAttribute('aria-label', 'Refresh')
    expect(screen.getByRole('button', { name: 'Log out' })).toHaveAttribute('aria-label', 'Log out')
  })
})

describe('open workspace (AC-23.143, AC-23.144, amended 2026-11-20)', () => {
  it('logs in with a name only and the popup has no Delete button', async () => {
    const api = createFakeApi({ delayMs: 0, persist: false, workspaceSeed: true, workspaceOpen: true })
    const { user } = open(api)
    expect(await screen.findByText(/Open demo workspace: anyone with the link can read sessions/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Access code')).toBeNull()
    await user.type(screen.getByLabelText('Your name'), 'Maria')
    await user.click(screen.getByRole('button', { name: 'Open workspace' }))
    await user.click(await screen.findByRole('button', { name: 'Open session Monthly cost review' }))
    expect(await screen.findByRole('button', { name: 'Download report (PDF)' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Delete session' })).toBeNull()
  })
})
