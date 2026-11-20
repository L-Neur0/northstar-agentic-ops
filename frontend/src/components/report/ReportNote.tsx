/**
 * The note box of a report part: the server's note under a part heading, or the catalogue note
 * above Parts 5 and 6 (spec 23 §11.11.1–2; AC-23.93, AC-23.97).
 * Why: a part that failed, was simplified or is thin must say so in words, and the reader must
 * see the difference between a warning and a plain note without relying on colour.
 * Rules: kinds `failed` and `error` are warnings (`AlertTriangle`, "Warning"), every other kind is
 * a note (`Info`, "Note"); the text is always the server's (or the page's fixed fallback for a
 * missing part). Must not: write its own wording for a server note, or render Markdown or HTML.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57, AC-23.102).
 */
import { AlertTriangle, Info } from 'lucide-react'

export function ReportNoteBox({ kind, text }: { kind: string; text: string }) {
  const warning = kind === 'failed' || kind === 'error'
  const Icon = warning ? AlertTriangle : Info
  return (
    <div
      data-note-kind={kind}
      className={`my-2 flex items-start gap-2 rounded-md border px-3 py-2 text-sm ${
        warning ? 'border-warning/40 bg-warning-soft text-warning' : 'border-primary/30 bg-primary-soft text-link'
      }`}
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <p>
        <span className="font-semibold">{warning ? 'Warning' : 'Note'}: </span>
        {text}
      </p>
    </div>
  )
}
