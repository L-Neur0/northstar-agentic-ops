/**
 * The step grid of the workspace popup, now or as the expert first told it (spec 23 §19.4
 * block 2; AC-23.125, AC-23.126).
 * Why: the specialist reads every step field side by side and can compare the current steps with
 * the expert's first version, which documents or later answers may have changed.
 * Rules: **Now** is pressed by default; **As first told** is disabled with a visible reason when
 * the server kept no first version; the table has a caption, header scopes and a sticky field
 * column, inside a focusable labelled region that scrolls sideways; each cell shows the server's
 * display text (Q15) and a muted line with the source word and the status icon and word.
 * Must not: format or edit a value; no cell is an input.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.141).
 */
import { useId, useState } from 'react'
import { STATUS } from '../process-discovery/fieldStatus'
import { formatCell, sourceWord } from '../../utils/workspaceFormat'
import type { FieldStatus } from '../../types/process-discovery'
import type { GridCell, StepGrid as Grid } from '../../types/workspace'

const TH = 'border-b border-line-strong bg-surface-muted px-2 py-1.5 text-left align-bottom font-semibold text-fg'
const TD = 'border-b border-line px-2 py-1.5 align-top text-fg'
const TOGGLE =
  'px-3 py-1 text-xs font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:text-subtle'

function Cell({ cell }: { cell: GridCell }) {
  const look = cell.status ? (STATUS[cell.status as FieldStatus] ?? null) : null
  const source = sourceWord(cell.source)
  return (
    <td className={`${TD} min-w-[12rem]`}>
      <span className="whitespace-pre-wrap">{formatCell(cell.value)}</span>
      {(source || look) && (
        <span className="mt-1 flex items-center gap-1 text-xs text-muted">
          {source}
          {source && look && ' · '}
          {look && (
            <>
              <look.Icon className={`h-3.5 w-3.5 shrink-0 ${look.colour}`} aria-hidden="true" />
              {look.label}
            </>
          )}
        </span>
      )}
    </td>
  )
}

export function StepGrid({ steps, rawSteps }: { steps: Grid; rawSteps: Grid | null }) {
  const [first, setFirst] = useState(false)
  const reasonId = useId()
  const grid = first && rawSteps ? rawSteps : steps
  const pressed = first && rawSteps !== null

  return (
    <section aria-labelledby={`${reasonId}-title`}>
      <div className="flex flex-wrap items-center gap-3">
        <h3 id={`${reasonId}-title`} className="text-base font-semibold text-fg">
          Steps
        </h3>
        <div role="group" aria-label="Step version" className="inline-flex overflow-hidden rounded-md border border-line-strong">
          <button
            type="button"
            aria-pressed={!pressed}
            onClick={() => setFirst(false)}
            className={`${TOGGLE} ${!pressed ? 'bg-primary text-primary-contrast' : 'bg-surface text-fg hover:bg-surface-muted'}`}
          >
            Now
          </button>
          <button
            type="button"
            aria-pressed={pressed}
            disabled={rawSteps === null}
            aria-describedby={rawSteps === null ? reasonId : undefined}
            onClick={() => setFirst(true)}
            className={`${TOGGLE} border-l border-line-strong ${pressed ? 'bg-primary text-primary-contrast' : 'bg-surface text-fg hover:bg-surface-muted'}`}
          >
            As first told
          </button>
        </div>
        {rawSteps === null && (
          <p id={reasonId} className="text-xs text-muted">
            The expert's first version was not kept, because nothing changed it.
          </p>
        )}
      </div>
      {grid.stepNames.length === 0 ? (
        <p className="mt-2 text-sm text-muted">No steps yet.</p>
      ) : (
        <div role="region" aria-label="Step grid" tabIndex={0} className="mt-2 overflow-x-auto rounded-md border border-line">
          <table className="w-full border-collapse text-left text-sm">
            <caption className="px-2 py-1.5 text-left text-xs text-muted">
              {pressed ? 'Steps as the expert first told them, one column per step' : 'Steps now, one column per step'}
            </caption>
            <thead>
              <tr>
                <th scope="col" className={`${TH} sticky left-0 z-10`}>
                  Field
                </th>
                {grid.stepNames.map((name, i) => (
                  <th key={i} scope="col" className={TH}>
                    Step {i + 1} · {name || '—'}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {grid.rows.map((row) => (
                <tr key={row.key}>
                  <th scope="row" className={`${TD} sticky left-0 z-10 bg-surface font-medium text-muted`}>
                    {row.label}
                  </th>
                  {grid.stepNames.map((_, i) => (
                    <Cell key={i} cell={row.cells[i] ?? { value: '', source: null, status: null }} />
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
