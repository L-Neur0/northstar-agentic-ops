/**
 * Tests for the Conversation tab (spec 23 §19.5; AC-23.131, AC-23.132).
 * Why: each conversation fetch is an audit line on the server, so it must happen only when the tab
 * is opened, once per popup; and the transcript must render safely with clear speakers.
 * What: the popup against the fake API (call counting with a spy) and the view with fixtures.
 * Must not: run Mermaid.
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConversationView } from './ConversationView'
import { SessionDialog } from './SessionDialog'
import { renderWithProviders } from '../../test/render'
import { reviewRow, stubMap, workspaceFake } from '../../test/fixtures/workspace'
import type { Message } from '../../types/process-discovery'

afterEach(() => {
  vi.restoreAllMocks()
  sessionStorage.clear()
})

function openPopup() {
  const api = workspaceFake()
  const spy = vi.spyOn(api, 'reviewConversation')
  renderWithProviders(
    <SessionDialog row={reviewRow({ id: 'seed-cost-review' })} mapRenderer={stubMap} onClose={vi.fn()} onDeleted={vi.fn()} onSessionEnded={vi.fn()} />,
    { api },
  )
  return { spy, user: userEvent.setup() }
}

describe('fetched on demand (AC-23.131)', () => {
  it('never opening the tab makes no call', async () => {
    const { spy } = openPopup()
    await screen.findByRole('tab', { name: 'Session' })
    expect(spy).not.toHaveBeenCalled()
  })

  it('opening the tab calls once; switching back and forth does not call again', async () => {
    const { spy, user } = openPopup()
    await user.click(await screen.findByRole('tab', { name: 'Conversation' }))
    expect(await screen.findByRole('list', { name: /^Conversation, \d+ messages$/ })).toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: 'Session' }))
    await user.click(screen.getByRole('tab', { name: 'Conversation' }))
    await screen.findByRole('list', { name: /^Conversation/ })
    expect(spy).toHaveBeenCalledTimes(1)
  })
})

describe('rendering (AC-23.132)', () => {
  const messages: Message[] = [
    { id: '1', role: 'agent', text: 'Hello! **Which department** do you work in?', at: '2026-11-20T14:05:00' },
    { id: '2', role: 'expert', text: '<script>window.hacked = true</script>Finance', at: '2026-11-20T14:06:00' },
  ]

  it('shows the notice, the ordered list with speakers and date and time, safe Markdown', () => {
    const { container } = render(<ConversationView messages={messages} loading={false} error={null} onRetry={vi.fn()} />)
    expect(screen.getByText('The expert was told that the team may read this conversation. Opening it is logged.')).toBeInTheDocument()
    const list = screen.getByRole('list', { name: 'Conversation, 2 messages' })
    expect(list.tagName).toBe('OL')
    const items = within(list).getAllByRole('listitem')
    expect(items[0]).toHaveTextContent('Agent')
    expect(items[0]).toHaveTextContent('20 Nov 2026, 14:05')
    expect(within(items[0]).getByText('Which department').tagName).toBe('STRONG')
    expect(items[1]).toHaveTextContent('Expert')
    expect(items[1]).toHaveTextContent('<script>window.hacked = true</script>Finance')
    expect(container.querySelector('script')).toBeNull()
    expect((window as unknown as { hacked?: boolean }).hacked).toBeUndefined()
  })

  it('loading, empty and error states', () => {
    const retry = vi.fn()
    const { rerender } = render(<ConversationView messages={undefined} loading error={null} onRetry={retry} />)
    expect(screen.getByRole('status')).toHaveTextContent('Loading the conversation…')
    rerender(<ConversationView messages={[]} loading={false} error={null} onRetry={retry} />)
    expect(screen.getByText('No messages in this session.')).toBeInTheDocument()
    rerender(<ConversationView messages={undefined} loading={false} error={new Error('x')} onRetry={retry} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Something went wrong. Please try again.')
  })
})
