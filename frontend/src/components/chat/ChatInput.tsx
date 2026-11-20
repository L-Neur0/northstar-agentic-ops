/**
 * The composer of the interview chat (spec 23 §3.7; AC-23.20).
 * Why: the chat input, without an upload panel: an auto-growing textarea
 * (max 120 px), Enter sends, Shift+Enter adds a line, and focus returns after a send.
 * Rules: controlled (`value`/`onChange`) so the page can put the text back after a failed send;
 * trimmed empty text and text above 16,000 characters (spec 15 route 5) cannot be sent; a counter
 * appears from 14,400 characters. Part 2: a `leading` slot on the left of the box holds the "+"
 * button that adds a document (spec 23 §11.1; AC-23.103). Must not call the API itself.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57).
 */
import { useEffect, useRef, type KeyboardEvent, type ReactNode } from 'react'
import { ArrowUp } from 'lucide-react'
import { MESSAGE_MAX_CHARS } from '../../types/process-discovery'

const COUNTER_FROM = 14_400
const fmt = (n: number) => n.toLocaleString('en-US')

interface ChatInputProps {
  value: string
  onChange: (value: string) => void
  onSend: (text: string) => void
  disabled: boolean
  /** Shown on the left of the message box (the "+" button). */
  leading?: ReactNode
}

export function ChatInput({ value, onChange, onSend, disabled, leading }: ChatInputProps) {
  const ref = useRef<HTMLTextAreaElement>(null)
  /** True between a send and the composer being enabled again: then focus comes back. */
  const refocus = useRef(false)
  const tooLong = value.length > MESSAGE_MAX_CHARS
  const canSend = !disabled && !tooLong && value.trim().length > 0

  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`
  }, [value])

  useEffect(() => {
    if (!disabled && refocus.current) {
      refocus.current = false
      ref.current?.focus()
    }
  }, [disabled])

  const send = () => {
    if (!canSend) return
    refocus.current = true
    onSend(value.trim())
    ref.current?.focus()
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className="border-t border-line bg-surface">
      <div className="flex items-end gap-2 px-4 py-3">
        {leading}
        <textarea
          ref={ref}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={disabled}
          rows={1}
          aria-label="Message"
          placeholder="Type your answer… (Enter to send, Shift+Enter for a new line)"
          className={`max-h-[120px] min-h-[2.5rem] flex-1 resize-none rounded-lg border bg-surface px-3 py-2 text-sm leading-6 text-fg placeholder:text-subtle focus:outline-none focus:ring-2 focus:ring-primary disabled:bg-surface-muted disabled:text-subtle ${
            tooLong ? 'border-danger' : value.length >= COUNTER_FROM ? 'border-warning' : 'border-line-strong'
          }`}
        />
        <button
          type="button"
          onClick={send}
          disabled={!canSend}
          aria-label="Send message"
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-contrast hover:bg-primary-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:bg-line-strong"
        >
          <ArrowUp className="h-5 w-5" aria-hidden="true" />
        </button>
      </div>
      {value.length >= COUNTER_FROM && (
        <p className={`px-4 pb-2 text-right text-xs ${tooLong ? 'font-medium text-danger' : 'text-warning'}`} aria-live="polite">
          {tooLong
            ? `This message is too long: ${fmt(value.length)} / ${fmt(MESSAGE_MAX_CHARS)} characters.`
            : `${fmt(value.length)} / ${fmt(MESSAGE_MAX_CHARS)} characters`}
        </p>
      )}
    </div>
  )
}
