/**
 * One chat message (spec 23 §3.7; AC-23.24).
 * Why: the bubble: the agent on the left (neutral bubble, `Bot` icon, label
 * "Agent"), the expert on the right (primary tint, label "You"), Markdown via react-markdown and
 * remark-gfm with compact renderers tuned for a bubble.
 * Rules: raw HTML is never rendered (no rehype-raw); links come from model output, so they open in
 * a new tab with `rel="noopener noreferrer"`. The expert's text keeps its line breaks.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57).
 */
import type { ReactNode } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Bot, User } from 'lucide-react'
import type { Message } from '../../types/process-discovery'

const markdown: Components = {
  p: ({ children }: { children?: ReactNode }) => <p className="whitespace-pre-wrap [&:not(:first-child)]:mt-2">{children}</p>,
  ul: ({ children }: { children?: ReactNode }) => <ul className="mt-1 list-disc pl-5">{children}</ul>,
  ol: ({ children, start }: { children?: ReactNode; start?: number }) => (
    <ol start={start} className="mt-1 list-decimal pl-6">
      {children}
    </ol>
  ),
  h1: ({ children }: { children?: ReactNode }) => <strong className="my-1 block">{children}</strong>,
  h2: ({ children }: { children?: ReactNode }) => <strong className="my-1 block">{children}</strong>,
  h3: ({ children }: { children?: ReactNode }) => <strong className="my-1 block">{children}</strong>,
  code: ({ children }: { children?: ReactNode }) => <code className="rounded bg-surface-strong px-1 text-[0.8125rem]">{children}</code>,
  a: ({ href, children }: { href?: string; children?: ReactNode }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" className="underline">
      {children}
    </a>
  ),
}

const time = (iso: string) => {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export function ChatMessageBubble({ message }: { message: Message }) {
  const isExpert = message.role === 'expert'
  return (
    <div className={`flex items-start gap-3 px-4 py-2 ${isExpert ? 'flex-row-reverse' : ''}`}>
      <div
        aria-hidden="true"
        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${isExpert ? 'bg-primary text-primary-contrast' : 'bg-surface-strong text-fg'}`}
      >
        {isExpert ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </div>
      <div className={`flex max-w-[75%] flex-col ${isExpert ? 'items-end' : 'items-start'}`}>
        <span className="mb-0.5 text-xs font-medium text-subtle">{isExpert ? 'You' : 'Agent'}</span>
        <div
          className={`break-words rounded-xl px-4 py-2.5 text-sm leading-6 ${
            isExpert ? 'whitespace-pre-wrap bg-bubble-expert text-fg ring-1 ring-inset ring-primary/30' : 'bg-bubble-agent text-fg'
          }`}
        >
          {isExpert ? message.text : <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdown}>{message.text}</ReactMarkdown>}
        </div>
        <span className="mt-0.5 text-[0.6875rem] text-subtle">{time(message.at)}</span>
      </div>
    </div>
  )
}
