/**
 * Page tests for My processes (spec 23 §3.3; AC-23.2, AC-23.3, AC-23.7–23.13).
 * Why: Home is where the expert finds sessions, ideas, the resume link and the delete-my-data
 * action; each list has its own loading, error-with-Retry and empty state, and destructive
 * actions ask first.
 * Rules: rendered through the router with an injected fake API; storage is reset between tests.
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useLocation } from 'react-router-dom'
import App from '../App'
import { renderWithProviders } from '../test/render'
import { createFakeApi } from '../services/fakeApi'
import { ApiError, type DiscoveryApi } from '../services/api'
import { buildSession, summary } from '../test/fixtures/sessions'
import { DISPLAY_NAME_KEY } from '../access/displayName'
import { INTRO_SEEN_KEY } from '../components/process-discovery/introStorage'
import { consumeResumeFragment, getVisitorKey, resetVisitorKeyForTests } from '../access/visitorKey'
import type { Idea } from '../types/process-discovery'

function Probe() {
  return <div data-testid="path">{useLocation().pathname}</div>
}

const hoursAgo = (h: number) => new Date(Date.now() - h * 3_600_000).toISOString()

const idea: Idea = {
  id: 'i-1',
  name: 'Chasing site managers',
  words: 'I chase the site managers every Friday',
  status: 'open',
  fromSessionId: 's-1',
  startedSessionId: null,
  createdAt: hoursAgo(1),
}

function stubbedApi(): DiscoveryApi {
  const api = createFakeApi({ delayMs: 0, persist: false })
  vi.spyOn(api, 'listSessions').mockResolvedValue({
    sessions: [
      summary({ id: 's-1', status: 'finished', phase: 'finished', processName: 'Monthly cost review', score: 0.86, reportStatus: 'validated', updatedAt: hoursAgo(2) }),
      summary({ id: 's-2', status: 'active', phase: 'measure', processName: null, score: 0.31, updatedAt: hoursAgo(26) }),
      summary({ id: 's-3', status: 'no_candidate', phase: 'no_candidate', processName: 'Booking travel', score: 0.12, updatedAt: hoursAgo(72) }),
    ],
  })
  vi.spyOn(api, 'listIdeas').mockResolvedValue({ ideas: [idea, { ...idea, id: 'i-2', name: 'Started one', status: 'started' }] })
  return api
}

const renderHome = (api: DiscoveryApi = stubbedApi()) =>
  renderWithProviders(
    <>
      <App />
      <Probe />
    </>,
    { api, route: '/' },
  )

const rows = () => within(screen.getByRole('table', { name: 'Sessions' })).getAllByRole('row').slice(1)

beforeEach(() => {
  resetVisitorKeyForTests()
  localStorage.setItem(INTRO_SEEN_KEY, 'true')
})
afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
  resetVisitorKeyForTests()
})

describe('sessions table (AC-23.7, AC-23.8)', () => {
  it('lists name, status, completeness and time in server order', async () => {
    renderHome()
    await screen.findByText('Monthly cost review')
    const [a, b, c] = rows()
    expect(a).toHaveTextContent('Monthly cost review')
    expect(a).toHaveTextContent('Mapped · Validated by IT')
    expect(a).toHaveTextContent('86 %')
    expect(a).toHaveTextContent('2 hours ago')
    expect(b).toHaveTextContent('Not named yet')
    expect(b).toHaveTextContent('In progress · Measures')
    expect(b).toHaveTextContent('31 %')
    expect(b).toHaveTextContent('yesterday')
    expect(c).toHaveTextContent('Ended · nothing to map')
    expect(screen.getAllByRole('columnheader').map((h) => h.getAttribute('scope'))).toContain('col')
  })

  it('offers Continue, Open report and Delete by status', async () => {
    renderHome()
    await screen.findByText('Monthly cost review')
    const [a, b, c] = rows()
    expect(within(a).getByRole('link', { name: 'Open report' })).toHaveAttribute('href', '/report/s-1')
    expect(within(b).getByRole('link', { name: 'Continue' })).toHaveAttribute('href', '/process-discovery/s-2')
    expect(within(c).queryByRole('link')).not.toBeInTheDocument()
    for (const r of [a, b, c]) expect(within(r).getByRole('button', { name: /Delete/ })).toBeInTheDocument()
  })

  it('asks before deleting, then deletes and refreshes', async () => {
    const user = userEvent.setup()
    const api = stubbedApi()
    const del = vi.spyOn(api, 'deleteSession').mockResolvedValue(undefined)
    renderHome(api)
    await screen.findByText('Monthly cost review')
    await user.click(within(rows()[0]).getByRole('button', { name: /Delete/ }))
    const dialog = screen.getByRole('alertdialog', { name: 'Delete this session?' })
    expect(dialog).toHaveTextContent('This cannot be undone.')
    await user.click(within(dialog).getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(del).toHaveBeenCalledWith('s-1'))
    await waitFor(() => expect(api.listSessions).toHaveBeenCalledTimes(2))
  })
})

describe('loading failures (AC-23.9)', () => {
  it('shows an error with Retry, not an empty list', async () => {
    const user = userEvent.setup()
    const api = stubbedApi()
    vi.mocked(api.listSessions).mockReset().mockRejectedValueOnce(new ApiError(0, 'network', '')).mockResolvedValue({ sessions: [] })
    renderHome(api)
    expect(await screen.findByText(/Could not load your sessions/)).toBeInTheDocument()
    expect(screen.queryByText(/No sessions yet/)).not.toBeInTheDocument()
    await user.click(screen.getAllByRole('button', { name: 'Retry' })[0])
    expect(await screen.findByText(/No sessions yet/)).toBeInTheDocument()
  })
})

describe('start a new interview (AC-23.10)', () => {
  it('sends the stored first name and opens the new session', async () => {
    const user = userEvent.setup()
    const api = stubbedApi()
    const create = vi.spyOn(api, 'createSession').mockResolvedValue(buildSession({ id: 'new-1' }))
    vi.spyOn(api, 'getSession').mockResolvedValue(buildSession({ id: 'new-1' }))
    renderHome(api)
    await user.type(screen.getByLabelText(/First name/), 'Anna')
    expect(localStorage.getItem(DISPLAY_NAME_KEY)).toBe('Anna')
    await user.click(screen.getByRole('button', { name: 'Start a new interview' }))
    await waitFor(() => expect(create).toHaveBeenCalledWith({ displayName: 'Anna' }))
    await waitFor(() => expect(screen.getByTestId('path')).toHaveTextContent('/process-discovery/new-1'))
  })

  it('omits an empty first name', async () => {
    const user = userEvent.setup()
    const api = stubbedApi()
    const create = vi.spyOn(api, 'createSession').mockResolvedValue(buildSession({ id: 'new-2' }))
    vi.spyOn(api, 'getSession').mockResolvedValue(buildSession({ id: 'new-2' }))
    renderHome(api)
    await user.click(screen.getByRole('button', { name: 'Start a new interview' }))
    await waitFor(() => expect(create).toHaveBeenCalledWith({ displayName: undefined }))
  })
})

describe('ideas (AC-23.11)', () => {
  it('lists open ideas; Map this starts one; Delete asks then removes', async () => {
    const user = userEvent.setup()
    const api = stubbedApi()
    const start = vi.spyOn(api, 'startIdea').mockResolvedValue(buildSession({ id: 'from-idea' }))
    vi.spyOn(api, 'getSession').mockResolvedValue(buildSession({ id: 'from-idea' }))
    const del = vi.spyOn(api, 'deleteIdea').mockResolvedValue(undefined)
    renderHome(api)
    expect(await screen.findByText('Chasing site managers')).toBeInTheDocument()
    expect(screen.getByText(/I chase the site managers every Friday/)).toBeInTheDocument()
    expect(screen.queryByText('Started one')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Delete idea Chasing site managers/ }))
    await user.click(within(screen.getByRole('alertdialog', { name: 'Delete this idea?' })).getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(del).toHaveBeenCalledWith('i-1'))
    await user.click(screen.getByRole('button', { name: 'Map this' }))
    await waitFor(() => expect(start).toHaveBeenCalledWith('i-1'))
    await waitFor(() => expect(screen.getByTestId('path')).toHaveTextContent('/process-discovery/from-idea'))
  })
})

describe('resume link (AC-23.12)', () => {
  it('reveals the private link with Copy and the warning', async () => {
    const user = userEvent.setup()
    renderHome()
    await user.click(screen.getByRole('button', { name: 'Show resume link' }))
    const link = `${window.location.origin}/#k=${getVisitorKey()}`
    expect(screen.getByRole('textbox', { name: 'Resume link' })).toHaveValue(link)
    expect(screen.getByText('Anyone with this link sees your processes. Keep it private.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Copy' }))
    await expect(navigator.clipboard.readText()).resolves.toBe(link)
    expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument()
  })
})

describe('delete all my data (AC-23.13)', () => {
  it('asks with an alert dialog, deletes, refreshes and reports the counts', async () => {
    const user = userEvent.setup()
    const api = stubbedApi()
    const wipe = vi.spyOn(api, 'deleteMyData').mockResolvedValue({ sessions: 3, ideas: 1 })
    renderHome(api)
    await screen.findByText('Monthly cost review')
    await user.click(screen.getByRole('button', { name: 'Delete all my data' }))
    const dialog = screen.getByRole('alertdialog')
    expect(dialog).toHaveTextContent('This deletes every session and idea saved with this browser. It cannot be undone.')
    await user.click(within(dialog).getByRole('button', { name: 'Delete everything' }))
    await waitFor(() => expect(wipe).toHaveBeenCalled())
    expect(await screen.findByText('Deleted 3 sessions and 1 idea.')).toBeInTheDocument()
    await waitFor(() => expect(api.listIdeas).toHaveBeenCalledTimes(2))
  })
})

describe('notices (AC-23.2, AC-23.3)', () => {
  it('shows the storage notice when localStorage throws', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    renderHome()
    expect(
      await screen.findByText('Your browser does not keep data for this site. Use the resume link below to come back to your processes.'),
    ).toBeInTheDocument()
  })

  it('shows the resume notice after opening a resume link', async () => {
    window.history.replaceState(null, '', '/#k=Abcdefghijklmnopqrstu_')
    consumeResumeFragment()
    renderHome()
    expect(await screen.findByText('You opened a resume link. You now see the processes saved with it.')).toBeInTheDocument()
    window.history.replaceState(null, '', '/')
  })
})
