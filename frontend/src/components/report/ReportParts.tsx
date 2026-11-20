/**
 * The cover and the eleven parts of the discovery report on screen (spec 23 §11.11; spec 20 v3
 * §3.3; AC-23.85, AC-23.87, AC-23.92–23.96, AC-23.98).
 * Why: the expert reads the same report the PDF prints, part by part, in plain words and tables
 * that work with a screen reader and on a phone.
 * Rules: every number, label and sentence is the server's string, rendered as plain text (no
 * Markdown, no HTML); tables have captions and header scopes; wide tables scroll inside a
 * focusable, labelled region; levels and AI fit carry an icon and a word, never colour alone;
 * hours only (no euro field exists). Must not: format, compute or reorder any value, or invent an
 * empty group the server did not send.
 * Part 3 (spec 23 §19.4 rule 3): `RecommendedRoute` and `OpportunityList` take `headingLevel`
 * (the level of the part heading around them; default 2), so the workspace popup can nest them
 * under its own `<h3>` part headings.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57, AC-23.102).
 */
import { createElement, type ReactNode } from 'react'
import { Bot, Handshake, HelpCircle, SignalHigh, SignalLow, SignalMedium, User, type LucideIcon } from 'lucide-react'
import { Pill } from '../ui/Pill'
import { ReportNoteBox } from './ReportNote'
import { ProcessMap, type MapRenderer } from './ProcessMap'
import type {
  AssessmentPart,
  AtAGlancePart,
  FieldsPart,
  GapsPart,
  MapPart,
  PathPart,
  PotentialPart,
  ReadinessPart,
  ReportCover as Cover,
  ReportField,
  RoutePart,
  StepsPart,
} from '../../types/report'

const TABLE = 'w-full border-collapse text-left text-sm'
const TH = 'border-b border-line-strong bg-surface-muted px-2 py-1.5 align-bottom font-semibold text-fg'
const TD = 'border-b border-line px-2 py-1.5 align-top text-fg'
const H3 = 'mt-4 mb-1 text-base font-semibold text-fg break-after-avoid'

/** A heading one level below the part heading (`headingLevel` 2 → `<h3>`, 3 → `<h4>`). */
function SubHeading({ level, className = H3, children }: { level: 2 | 3; className?: string; children: ReactNode }) {
  return createElement(`h${level + 1}`, { className }, children)
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

export function AtAGlance({ part }: { part: AtAGlancePart }) {
  return (
    <div>
      <p className="text-xl font-semibold text-fg">{part.hours}</p>
      {part.routeHeadline && (
        <p className="mt-2 text-sm text-fg">
          <span className="font-semibold">Recommended route: </span>
          {part.routeHeadline}
        </p>
      )}
      {part.top.length > 0 && (
        <>
          <h3 className={H3}>Top opportunities</h3>
          <List items={part.top.map((t) => `${t.title} · ${t.stepsLabel} · ${t.hours}`)} />
        </>
      )}
      {part.prepare.length > 0 && (
        <>
          <h3 className={H3}>To prepare</h3>
          <List items={part.prepare} />
        </>
      )}
    </div>
  )
}

function fieldQuoteLabel(field: ReportField): string {
  if (field.source === 'document') return 'from a document'
  if (field.source === 'expert') return "the expert's words"
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

const FIT: Record<string, LucideIcon> = { automate: Bot, assist: Handshake, human: User }

export function StepAssessmentTable({ part }: { part: StepsPart }) {
  return (
    <div>
      {part.catalogueNote && <ReportNoteBox kind="missing" text={part.catalogueNote} />}
      {part.rows.length > 0 && (
        <ScrollRegion label="Step-by-step assessment">
          <table className={TABLE}>
            <caption className="pb-1 text-left text-xs text-muted">AI fit and route for each step</caption>
            <thead>
              <tr>
                {['Step', 'Hours a year', 'AI fit', 'Route', 'Why this route', 'Reason', 'Evidence'].map((h) => (
                  <th key={h} scope="col" className={TH}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {part.rows.map((row) => {
                const Icon = (row.fit && FIT[row.fit]) || HelpCircle
                return (
                  <tr key={row.number}>
                    <td className={TD}>
                      Step {row.number} · {row.name}
                    </td>
                    <td className={TD}>{row.hours}</td>
                    <td className={TD}>
                      <span className="inline-flex items-center gap-1">
                        <Icon className="h-4 w-4 shrink-0 text-link" aria-hidden="true" />
                        {row.fitLabel}
                      </span>
                    </td>
                    <td className={TD}>{row.routeName}</td>
                    <td className={TD}>{row.routeReason}</td>
                    <td className={TD}>{row.reason}</td>
                    <td className={TD}>
                      <Quote text={row.evidence} label={row.evidenceLabel} />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </ScrollRegion>
      )}
    </div>
  )
}

export function RecommendedRoute({ part, headingLevel = 2 }: { part: RoutePart; headingLevel?: 2 | 3 }) {
  return (
    <div>
      {part.catalogueNote && <ReportNoteBox kind="missing" text={part.catalogueNote} />}
      {part.headline && <p className="text-base font-medium text-fg">{part.headline}</p>}
      {part.groups.map((g) => (
        <div key={g.key}>
          <SubHeading level={headingLevel}>{g.title}</SubHeading>
          <List
            items={g.items.map((item) =>
              [`Step ${item.number} · ${item.name}`, item.hours, item.routeName || item.reason].filter(Boolean).join(' · '),
            )}
          />
        </div>
      ))}
      {part.prepare.length > 0 && (
        <>
          <SubHeading level={headingLevel}>What to have in place</SubHeading>
          <List items={part.prepare} />
        </>
      )}
    </div>
  )
}

export function OpportunityList({ part, headingLevel = 2 }: { part: AssessmentPart; headingLevel?: 2 | 3 }) {
  return (
    <div>
      {part.summary && <p className="text-sm text-fg">{part.summary}</p>}
      {part.opportunities.map((o) => (
        <article key={o.id} className="mt-4 rounded-md border border-line p-3 break-inside-avoid">
          <SubHeading level={headingLevel} className="text-base font-semibold text-fg">
            {o.title}
          </SubHeading>
          <p className="text-xs text-muted">
            {o.stepsLabel} · {o.typeLabel} · Impact {o.impact} · Feasibility {o.feasibility}
          </p>
          <dl className="mt-2 grid grid-cols-1 gap-x-3 gap-y-1 text-sm sm:grid-cols-[minmax(9rem,auto)_1fr]">
            {(
              [
                ['What changes', o.whatChanges],
                ['How', o.how],
                ['Prepare first', o.prepareFirst],
                ['Why this impact', o.impactReason],
                ['Why this feasibility', o.feasibilityReason],
              ] as const
            )
              .filter(([, v]) => v)
              .map(([term, value]) => (
                <div key={term} className="contents">
                  <dt className="font-medium text-muted">{term}</dt>
                  <dd className="text-fg">{value}</dd>
                </div>
              ))}
            {o.evidence && (
              <div className="contents">
                <dt className="font-medium text-muted">Evidence</dt>
                <dd>
                  <Quote text={o.evidence} label={o.evidenceLabel} />
                </dd>
              </div>
            )}
            {o.review && (
              <div className="contents">
                <dt className="font-medium text-muted">Review</dt>
                <dd className="text-fg">{o.review}</dd>
              </div>
            )}
          </dl>
        </article>
      ))}
      {part.stayHuman.length > 0 && (
        <>
          <SubHeading level={headingLevel}>Steps that stay with people</SubHeading>
          <ul className="ml-5 list-disc text-sm text-fg">
            {part.stayHuman.map((s, i) => (
              <li key={i}>
                {s.stepsLabel}: {s.reason} {s.evidence && <Quote text={s.evidence} label="the expert's words" />}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

export function HoursTables({ part }: { part: PotentialPart }) {
  return (
    <div>
      {part.steps.length > 0 && (
        <ScrollRegion label="Hours per step">
          <table className={TABLE}>
            <caption className="pb-1 text-left text-xs text-muted">Hours a year per step</caption>
            <thead>
              <tr>
                {['Step', 'Hours per run', 'Runs a year', 'Hours a year'].map((h) => (
                  <th key={h} scope="col" className={TH}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {part.steps.map((s) => (
                <tr key={s.number}>
                  <td className={TD}>
                    Step {s.number} · {s.name}
                  </td>
                  <td className={TD}>{s.hoursPerRun}</td>
                  <td className={TD}>{s.runsPerYear}</td>
                  <td className={TD}>{s.hoursPerYear}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th scope="row" colSpan={3} className={`${TD} font-semibold`}>
                  Total
                </th>
                <td className={`${TD} font-semibold`}>{part.totals.hours}</td>
              </tr>
            </tfoot>
          </table>
        </ScrollRegion>
      )}
      {part.opportunities.length > 0 && (
        <ScrollRegion label="Hours per opportunity">
          <table className={TABLE}>
            <caption className="pb-1 text-left text-xs text-muted">Hours a year of the steps each opportunity touches</caption>
            <thead>
              <tr>
                {['Opportunity', 'Steps', 'Hours of these steps'].map((h) => (
                  <th key={h} scope="col" className={TH}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {part.opportunities.map((o) => (
                <tr key={o.id}>
                  <td className={TD}>{o.title}</td>
                  <td className={TD}>{o.stepsLabel}</td>
                  <td className={TD}>{o.stepHours}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollRegion>
      )}
      {part.formulas.length > 0 && (
        <>
          <h3 className={H3}>How it is calculated</h3>
          <List items={part.formulas} />
        </>
      )}
      {part.assumptions.length > 0 && (
        <>
          <h3 className={H3}>Assumptions</h3>
          <List items={part.assumptions} />
        </>
      )}
      {part.problems.length > 0 && <List items={part.problems} />}
      {part.parkedLine && (
        <p data-testid="parked-line" className="mt-3 text-sm text-muted">
          {part.parkedLine}
        </p>
      )}
    </div>
  )
}

const LEVEL_ICON: Record<string, LucideIcon> = { high: SignalHigh, medium: SignalMedium, low: SignalLow }

export function ReadinessTable({ part }: { part: ReadinessPart }) {
  return (
    <div>
      <ScrollRegion label="Readiness checklist">
        <table className={TABLE}>
          <caption className="pb-1 text-left text-xs text-muted">Readiness by dimension</caption>
          <thead>
            <tr>
              {['Dimension', 'Question', 'Level', 'Why', 'To prepare', 'Specialist note'].map((h) => (
                <th key={h} scope="col" className={TH}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {part.dimensions.map((d) => {
              const Icon = LEVEL_ICON[d.level] ?? HelpCircle
              return (
                <tr key={d.key}>
                  <th scope="row" className={`${TD} font-medium`}>
                    {d.label}
                  </th>
                  <td className={TD}>{d.question}</td>
                  <td className={TD}>
                    <span className="inline-flex items-center gap-1">
                      <Icon className="h-4 w-4 shrink-0 text-link" aria-hidden="true" />
                      {d.levelLabel}
                    </span>
                  </td>
                  <td className={TD}>{d.reason}</td>
                  <td className={TD}>{d.toPrepare}</td>
                  <td className={TD}>{d.note}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </ScrollRegion>
      {part.footer && <p className="text-sm text-muted">{part.footer}</p>}
    </div>
  )
}

export function SuggestedPath({ part }: { part: PathPart }) {
  return (
    <div>
      {part.groups.map((g) => (
        <div key={g.key}>
          <h3 className={H3}>{g.title}</h3>
          {g.prepareLines.length > 0 && <List items={g.prepareLines} />}
          {g.items.length > 0 ? (
            <List items={g.items.map((i) => `${i.title} · ${i.stepsLabel} · ${i.stepHours}`)} />
          ) : (
            g.emptyText && <p className="text-sm text-muted">{g.emptyText}</p>
          )}
        </div>
      ))}
    </div>
  )
}

export function GapsAndSources({ part }: { part: GapsPart }) {
  return (
    <div>
      {part.fields.length > 0 && (
        <>
          <h3 className={H3}>Still open</h3>
          <List items={part.fields.map((f) => [f.label, f.value].filter(Boolean).join(': '))} />
        </>
      )}
      {part.documents.length > 0 && (
        <>
          <h3 className={H3}>Documents used</h3>
          <List items={part.documents.map((d) => `${d.name} · ${d.outcome}`)} />
        </>
      )}
      {part.closingNote && <p className="mt-3 text-sm text-muted">{part.closingNote}</p>}
    </div>
  )
}
