/**
 * The cover and the six parts of the discovery report on screen (report v2: spec 27 §3.1; spec 23
 * §11.11, amended 2026-11-21 (report v2); AC-23.85, AC-23.87, AC-23.92, AC-23.98, AC-23.153–23.156).
 * Why: the expert reads the same report the PDF prints, part by part, in plain words and tables
 * that work with a screen reader and on a phone.
 * Rules: every number, label and sentence is the server's string, rendered as plain text (no
 * Markdown, no HTML); tables have captions and header scopes; wide tables scroll inside a
 * focusable, labelled region; levels and AI fit carry an icon and a word, never colour alone;
 * hours only (no euro field exists). Must not: format, compute or reorder any value, or invent an
 * empty group the server did not send.
 * Levels (AI fit, the three questions, readiness) are the server's words with a signal icon, never
 * yes / no and never colour alone.
 * Part 3 (spec 23 §19.4 rule 3): `Feasibility` takes `headingLevel` (the level of the part heading
 * around it; default 2), so the workspace popup can nest its blocks under its own `<h3>` headings.
 * Short step walk (approved 2026-11-20): a field whose source is `agent` (proposed by code from the
 * expert's answers) labels its quote "suggested from the expert's answers".
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57, AC-23.102).
 */
import { createElement, useId, type ReactNode } from 'react'
import { HelpCircle, SignalHigh, SignalLow, SignalMedium, type LucideIcon } from 'lucide-react'
import { Pill } from '../ui/Pill'
import { ReportNoteBox } from './ReportNote'
import { ProcessMap, type MapRenderer } from './ProcessMap'
import type {
  FeasibilityPart,
  FieldsPart,
  MapPart,
  QuestionRow,
  ReadinessRow,
  ReportCover as Cover,
  ReportField,
  StepsPart,
  SummaryPart,
} from '../../types/report'

const TABLE = 'w-full border-collapse text-left text-sm'
const TH = 'border-b border-line-strong bg-surface-muted px-2 py-1.5 align-bottom font-semibold text-fg'
const TD = 'border-b border-line px-2 py-1.5 align-top text-fg'
const H3 = 'mt-4 mb-1 text-base font-semibold text-fg break-after-avoid'

/** A heading one level below the part heading (`headingLevel` 2 → `<h3>`, 3 → `<h4>`). */
function SubHeading({ level, className = H3, id, children }: { level: 2 | 3; className?: string; id?: string; children: ReactNode }) {
  return createElement(`h${level + 1}`, { className, id }, children)
}

function ScrollRegion({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div role="region" aria-label={label} tabIndex={0} className="my-2 overflow-x-auto print:overflow-visible">
      {children}
    </div>
  )
}

function List({ items }: { items: string[] }) {
  return (
    <ul className="ml-5 list-disc text-sm text-fg">
      {items.map((item, i) => (
        <li key={i}>{item}</li>
      ))}
    </ul>
  )
}

/** "the expert's words" / "from <document>" under a quote. */
function Quote({ text, label }: { text: string; label: string }) {
  if (!text) return null
  return (
    <span className="text-muted">
      “{text}”{label ? <span className="text-subtle"> ({label})</span> : null}
    </span>
  )
}

export function ReportCover({ cover }: { cover: Cover }) {
  const validated = /validated/i.test(cover.status)
  return (
    <header className="mb-6 border-b border-line pb-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted">
        Discovery report · {cover.productName} · {cover.companyName}
      </p>
      <div className="mt-1 flex flex-wrap items-center gap-3">
        <h2 className="text-2xl font-bold text-fg">{cover.processName}</h2>
        <Pill tone={validated ? 'success' : 'neutral'}>{cover.status}</Pill>
      </div>
      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm sm:grid-cols-[auto_1fr_auto_1fr]">
        {(
          [
            ['Department', cover.department],
            ['Cluster', cover.cluster],
            ['Region', cover.region],
            ['Process owner', cover.owner],
            ['Date', cover.date],
          ] as const
        ).map(([term, value]) => (
          <div key={term} className="contents">
            <dt className="text-muted">{term}</dt>
            <dd className="text-fg">{value}</dd>
          </div>
        ))}
      </dl>
    </header>
  )
}

/** Part 1: the server's summary sentences, one paragraph each (spec 27 §3.5). */
export function SummarySentences({ part }: { part: SummaryPart }) {
  return (
    <div className="flex flex-col gap-2 text-base text-fg">
      {part.sentences.map((sentence, i) => (
        <p key={i}>{sentence}</p>
      ))}
    </div>
  )
}

function fieldQuoteLabel(field: ReportField): string {
  if (field.source === 'document') return 'from a document'
  if (field.source === 'expert') return "the expert's words"
  if (field.source === 'agent') return "suggested from the expert's answers"
  return ''
}

export function ReportFields({ part }: { part: FieldsPart }) {
  return (
    <div>
      {part.notes.map((n, i) => (
        <ReportNoteBox key={i} kind={n.kind} text={n.text} />
      ))}
      <dl className="grid grid-cols-1 gap-x-4 gap-y-2 text-sm sm:grid-cols-[minmax(10rem,auto)_1fr]">
        {part.fields.map((f) => (
          <div key={f.key} className="contents">
            <dt className="font-medium text-muted">{f.label}</dt>
            <dd className="text-fg">
              {f.value}
              {f.quote && (
                <span className="block text-xs">
                  <Quote text={f.quote} label={fieldQuoteLabel(f)} />
                </span>
              )}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

export function StepTable({ part }: { part: MapPart }) {
  if (part.columns.length === 0) return null
  const rows = part.rowLabels.length > 0 ? part.rowLabels : (part.columns[0]?.cells.map((c) => c.label) ?? [])
  return (
    <ScrollRegion label="Step table">
      <table className={TABLE}>
        <caption className="pb-1 text-left text-xs text-muted">Steps of the process, one column per step</caption>
        <thead>
          <tr>
            <th scope="col" className={`${TH} sticky left-0`}>
              Field
            </th>
            {part.columns.map((c) => (
              <th key={c.number} scope="col" className={`${TH} min-w-[12rem]`}>
                Step {c.number} · {c.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((label, i) => (
            <tr key={label}>
              <th scope="row" className={`${TD} sticky left-0 bg-surface font-medium text-muted`}>
                {label}
              </th>
              {part.columns.map((c) => (
                <td key={c.number} className={TD}>
                  {(c.cells.find((cell) => cell.label === label) ?? c.cells[i])?.value ?? ''}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollRegion>
  )
}

export function MapAndSteps({ part, render }: { part: MapPart; render?: MapRenderer }) {
  return (
    <div>
      <ProcessMap diagram={part.diagram} caption={part.caption} render={render} />
      {part.systems.length > 0 && <p className="text-sm text-fg">Systems used: {part.systems.join(', ')}</p>}
      <StepTable part={part} />
    </div>
  )
}

/** A level as an icon plus the server's words; the key picks the icon only. */
const LEVEL_ICON: Record<string, LucideIcon> = {
  strong: SignalHigh,
  partial: SignalMedium,
  weak: SignalLow,
  high: SignalHigh,
  medium: SignalMedium,
  low: SignalLow,
}

function Level({ level, label }: { level: string | null; label: string }) {
  const Icon = (level && LEVEL_ICON[level]) || HelpCircle
  return (
    <span className="inline-flex items-center gap-1">
      <Icon className="h-4 w-4 shrink-0 text-link" aria-hidden="true" />
      {label}
    </span>
  )
}

/** Part 5: per step, AI fit (level), the signals behind it, route, why, hours and the expert's words. */
export function StepLevelTable({ part }: { part: StepsPart }) {
  return (
    <div>
      {part.catalogueNote && <ReportNoteBox kind="missing" text={part.catalogueNote} />}
      {part.rows.length > 0 && (
        <ScrollRegion label="Step-by-step assessment">
          <table className={TABLE}>
            <caption className="pb-1 text-left text-xs text-muted">AI fit, the reasons behind it and the route for each step</caption>
            <thead>
              <tr>
                {['Step', 'Hours a year', 'AI fit', 'Because', 'Route', 'Why', "The expert's words"].map((h) => (
                  <th key={h} scope="col" className={TH}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {part.rows.map((row) => (
                <tr key={row.number}>
                  <td className={TD}>
                    Step {row.number} · {row.name}
                  </td>
                  <td className={TD}>{row.hours}</td>
                  <td className={TD}>
                    <Level level={row.level} label={row.levelLabel} />
                  </td>
                  <td className={TD}>{row.because.length > 0 && <List items={row.because} />}</td>
                  <td className={TD}>
                    {row.routeName}
                    {row.routeReason && <span className="block text-xs text-muted">{row.routeReason}</span>}
                  </td>
                  <td className={TD}>{row.reason}</td>
                  <td className={TD}>
                    <Quote text={row.evidence} label={row.evidenceLabel} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollRegion>
      )}
    </div>
  )
}

/** Part 6 block A: the three guiding questions, each with the server's level words and why. */
export function QuestionsTable({ questions }: { questions: QuestionRow[] }) {
  if (questions.length === 0) return null
  return (
    <ScrollRegion label="The three questions table">
      <table className={TABLE}>
        <caption className="pb-1 text-left text-xs text-muted">The three questions</caption>
        <thead>
          <tr>
            {['Question', 'Level', 'Why'].map((h) => (
              <th key={h} scope="col" className={TH}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {questions.map((q) => (
            <tr key={q.key}>
              <th scope="row" className={`${TD} font-medium`}>
                {q.question}
              </th>
              <td className={TD}>
                <Level level={q.level} label={q.levelLabel} />
              </td>
              <td className={TD}>
                {q.why}
                {q.quote && (
                  <span className="block text-xs">
                    <Quote text={q.quote} label="the expert's words" />
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollRegion>
  )
}

/** Part 6 block B: the readiness checklist, one line per dimension. */
export function ReadinessTable({ rows, footer }: { rows: ReadinessRow[]; footer: string }) {
  return (
    <div>
      {rows.length > 0 && (
        <ScrollRegion label="Readiness checklist">
          <table className={TABLE}>
            <caption className="pb-1 text-left text-xs text-muted">Readiness by dimension</caption>
            <thead>
              <tr>
                {['Dimension', 'Level', 'To prepare'].map((h) => (
                  <th key={h} scope="col" className={TH}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => (
                <tr key={d.key}>
                  <th scope="row" className={`${TD} font-medium`}>
                    {d.label}
                  </th>
                  <td className={TD}>
                    <Level level={d.level} label={d.levelLabel} />
                  </td>
                  <td className={TD}>{d.toPrepare}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollRegion>
      )}
      {footer && <p className="text-sm text-muted">{footer}</p>}
    </div>
  )
}

/** Part 6, AI readiness and feasibility: A questions, B readiness, C bullets and the gaps line. */
export function Feasibility({ part, headingLevel = 2 }: { part: FeasibilityPart; headingLevel?: 2 | 3 }) {
  const bulletsId = useId()
  return (
    <div>
      <SubHeading level={headingLevel}>The three questions</SubHeading>
      <QuestionsTable questions={part.questions} />
      <SubHeading level={headingLevel}>Readiness</SubHeading>
      <ReadinessTable rows={part.readiness} footer={part.readinessFooter} />
      {(part.bullets.length > 0 || part.gaps) && (
        <SubHeading level={headingLevel} id={bulletsId}>
          Before starting and risks
        </SubHeading>
      )}
      {part.bullets.length > 0 && (
        <ul aria-labelledby={bulletsId} className="ml-5 list-disc text-sm text-fg">
          {part.bullets.map((item, i) => (
            <li key={i}>{item}</li>
          ))}
        </ul>
      )}
      {part.gaps && <p className="mt-3 text-xs text-muted">{part.gaps}</p>}
    </div>
  )
}
