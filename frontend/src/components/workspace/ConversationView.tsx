/**
 * The Conversation tab of the workspace popup (spec 23 §19.5; AC-23.131, AC-23.132).
 * Why: the specialist may read the full chat of a session (the expert was told so, product rule
 * 7); each opening is logged by the server, so the popup fetches it only when this tab is opened.
 * Rules: this view only renders; the popup owns the query (`enabled` after the first selection,
 * once per popup). A notice line says the reading is logged; messages keep server order in an
 * `<ol>` labelled with the count, rendered with the chat bubble ("Expert" / "Agent", date and
 * time); agent Markdown keeps the safe renderer, expert text is plain. Must not: copy, export or
 * search the conversation.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.141).
 */
import { RotateCcw } from 'lucide-react'
import { ChatMessageBubble } from '../chat/ChatMessageBubble'
import { Button } from '../ui/Button'
import { Spinner } from '../ui/Spinner'
import { workspaceErrorText } from '../../utils/discoveryErrors'
import type { Message } from '../../types/process-discovery'

const SPEAKERS = { expert: 'Expert', agent: 'Agent' }

export function ConversationView({
  messages,
  loading,
  error,
  onRetry,
}: {
  messages: Message[] | undefined
  loading: boolean
  error: unknown
  onRetry: () => void
}) {
  return (
    <div>
      <p className="mb-2 rounded-md border border-line bg-surface-muted px-3 py-2 text-xs text-muted">
        The expert was told that the team may read this conversation. Opening it is logged.
      </p>
      {loading ? (
        <p role="status" className="flex items-center gap-2 p-6 text-sm text-muted">
          <Spinner /> Loading the conversation…
        </p>
      ) : error ? (
        <div className="flex flex-col items-start gap-2 p-4">
          <p role="alert" className="text-sm text-danger">
            {workspaceErrorText(error)}
          </p>
          <Button icon={<RotateCcw className="h-4 w-4" aria-hidden="true" />} onClick={onRetry}>
            Retry
          </Button>
        </div>
      ) : !messages || messages.length === 0 ? (
        <p className="p-6 text-sm text-muted">No messages in this session.</p>
      ) : (
        <ol aria-label={`Conversation, ${messages.length} messages`} className="bg-page py-2">
          {messages.map((m) => (
            <li key={m.id}>
              <ChatMessageBubble message={m} speaker={SPEAKERS} showDate />
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
