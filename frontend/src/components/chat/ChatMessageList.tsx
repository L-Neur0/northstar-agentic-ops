/**
 * The conversation log of the interview page (spec 23 §3.7; AC-23.19).
 * Why: the message list: `role="log"` with `aria-live="polite"` so screen
 * readers hear new messages, auto-scroll to the newest message, and a "Thinking…" row while a turn
 * is in flight (after 20 s it says the turn can take up to two minutes).
 * Rules: one request per turn, no streaming or polling; this component only renders what it gets.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57).
 */
import { useEffect, useRef, useState } from 'react'
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

export function ChatMessageList({ messages, sending }: { messages: Message[]; sending: boolean }) {
  const bottom = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottom.current?.scrollIntoView?.({ behavior: 'smooth', block: 'end' })
  }, [messages.length, sending])

  return (
    <div role="log" aria-live="polite" aria-label="Conversation" className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto py-4">
      {messages.map((m) => (
        <ChatMessageBubble key={m.id} message={m} />
      ))}
      {sending && <ThinkingRow />}
      <div ref={bottom} />
    </div>
  )
}
