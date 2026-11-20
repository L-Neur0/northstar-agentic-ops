/**
 * The conversation log of the interview page (spec 23 §3.7, §11.1; AC-23.19, AC-23.73, AC-23.105).
 * Why: the message list: `role="log"` with `aria-live="polite"` so screen
 * readers hear new messages, auto-scroll to the newest message, and a "Thinking…" row while a turn
 * is in flight (after 20 s it says the turn can take up to two minutes).
 * Part 2: two slots, one under the first agent message (the document hint card) and one under the
 * last message (a system note such as the upload result sentence).
 * Rules: one request per turn, no streaming or polling; this component only renders what it gets.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57).
 */
import { Fragment, useEffect, useRef, useState, type ReactNode } from 'react'
import { ChatMessageBubble } from './ChatMessageBubble'
import { Spinner } from '../ui/Spinner'
import type { Message } from '../../types/process-discovery'

const SLOW_AFTER_MS = 20_000

function ThinkingRow() {
  const [slow, setSlow] = useState(false)
  useEffect(() => {
    const t = setTimeout(() => setSlow(true), SLOW_AFTER_MS)
    return () => clearTimeout(t)
  }, [])
  return (
    <div role="status" className="flex items-center gap-2 py-2 pl-14 pr-4 text-sm text-subtle">
      <Spinner size="sm" />
      <span>{slow ? 'Still working on it. This can take up to two minutes.' : 'Thinking…'}</span>
    </div>
  )
}

export function ChatMessageList({
  messages,
  sending,
  afterFirstAgent,
  systemNote,
}: {
  messages: Message[]
  sending: boolean
  afterFirstAgent?: ReactNode
  systemNote?: string | null
}) {
  const bottom = useRef<HTMLDivElement>(null)
  const firstAgent = messages.findIndex((m) => m.role === 'agent')

  useEffect(() => {
    bottom.current?.scrollIntoView?.({ behavior: 'smooth', block: 'end' })
  }, [messages.length, sending, systemNote])

  return (
    <div role="log" aria-live="polite" aria-label="Conversation" className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto py-4">
      {messages.map((m, i) => (
        <Fragment key={m.id}>
          <ChatMessageBubble message={m} />
          {i === firstAgent && afterFirstAgent}
        </Fragment>
      ))}
      {systemNote && (
        <p data-testid="chat-system-note" className="mx-4 my-1 self-center rounded-md bg-surface-muted px-3 py-1.5 text-center text-xs text-muted">
          {systemNote}
        </p>
      )}
      {sending && <ThinkingRow />}
      <div ref={bottom} />
    </div>
  )
}
