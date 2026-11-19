/**
 * Tests for the chat pieces of the interview page (spec 23 §3.7; AC-23.19, AC-23.20, AC-23.24).
 * Why: the conversation is the expert's way in; it must be announced politely to screen readers,
 * show when the agent is thinking, send on Enter only, respect the 16,000-character limit, and
 * never render HTML from a message.
 * Rules: the composer is controlled by its parent, so a failed send can restore the text.
 */
import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { ChatInput } from './ChatInput'
import { ChatMessageList } from './ChatMessageList'
import type { Message } from '../../types/process-discovery'

const msg = (id: string, role: Message['role'], text: string): Message => ({ id, role, text, at: '2026-11-19T08:00:00Z' })

function Composer({ onSend, disabled = false }: { onSend: (t: string) => void; disabled?: boolean }) {
  const [value, setValue] = useState('')
  return (
    <ChatInput
      value={value}
      onChange={setValue}
      disabled={disabled}
      onSend={(t) => {
        onSend(t)
        setValue('')
      }}
    />
  )
}

describe('ChatMessageList (AC-23.19, AC-23.24)', () => {
  it('is a polite log labelled Conversation, with Agent and You labels', () => {
    render(<ChatMessageList messages={[msg('1', 'agent', 'Hello'), msg('2', 'expert', 'Hi')]} sending={false} />)
    const log = screen.getByRole('log', { name: 'Conversation' })
    expect(log).toHaveAttribute('aria-live', 'polite')
    expect(screen.getByText('Agent')).toBeInTheDocument()
    expect(screen.getByText('You')).toBeInTheDocument()
  })

  it('shows Thinking… with role status while sending, then the slow message after 20 s', () => {
    vi.useFakeTimers()
    try {
      render(<ChatMessageList messages={[]} sending />)
      expect(screen.getByRole('status')).toHaveTextContent('Thinking…')
      act(() => {
        vi.advanceTimersByTime(20_000)
      })
      expect(screen.getByRole('status')).toHaveTextContent('Still working on it. This can take up to two minutes.')
    } finally {
      vi.useRealTimers()
    }
  })

  it('renders Markdown but never raw HTML; links open safely in a new tab', () => {
    const text = '**Bold** and a list:\n\n- one\n- two\n\n<script>alert(1)</script><img src=x onerror="alert(1)">\n\n[site](https://example.org)'
    const { container } = render(<ChatMessageList messages={[msg('1', 'agent', text)]} sending={false} />)
    expect(screen.getByText('Bold').tagName).toBe('STRONG')
    expect(screen.getAllByRole('listitem').length).toBeGreaterThanOrEqual(2)
    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('img')).toBeNull()
    const link = screen.getByRole('link', { name: 'site' })
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })
})

describe('ChatInput (AC-23.20)', () => {
  it('sends on Enter, adds a line on Shift+Enter and keeps focus', async () => {
    const user = userEvent.setup()
    const onSend = vi.fn()
    render(<Composer onSend={onSend} />)
    const box = screen.getByRole('textbox', { name: 'Message' })
    await user.click(box)
    await user.type(box, 'line one{Shift>}{Enter}{/Shift}line two')
    expect(box).toHaveValue('line one\nline two')
    expect(onSend).not.toHaveBeenCalled()
    await user.keyboard('{Enter}')
    expect(onSend).toHaveBeenCalledWith('line one\nline two')
    expect(box).toHaveValue('')
    expect(box).toHaveFocus()
  })

  it('does not send blank text', async () => {
    const user = userEvent.setup()
    const onSend = vi.fn()
    render(<Composer onSend={onSend} />)
    await user.type(screen.getByRole('textbox', { name: 'Message' }), '   {Enter}')
    expect(onSend).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled()
  })

  it('shows a counter near the limit and disables Send above 16,000 characters', () => {
    const onSend = vi.fn()
    render(<Composer onSend={onSend} />)
    const box = screen.getByRole('textbox', { name: 'Message' })
    fireEvent.change(box, { target: { value: 'a'.repeat(14_400) } })
    expect(screen.getByText('14,400 / 16,000 characters')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send message' })).toBeEnabled()
    fireEvent.change(box, { target: { value: 'a'.repeat(16_001) } })
    expect(screen.getByText(/too long/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send message' })).toBeDisabled()
    fireEvent.keyDown(box, { key: 'Enter' })
    expect(onSend).not.toHaveBeenCalled()
  })

  it('cannot send while disabled', () => {
    render(<Composer onSend={vi.fn()} disabled />)
    expect(screen.getByRole('textbox', { name: 'Message' })).toBeDisabled()
  })
})
