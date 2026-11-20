/**
 * The counts line and the table of discovery sessions (spec 23 §19.3; AC-23.116–23.119, AC-23.121).
 * Why: the specialist sees every session in one list, in the server's order, and opens one in
 * the read-only popup from its Process button.
 * Rules: eleven columns in the order of §19.3; rows in server order (never re-sorted); "Not named
 * yet" and "—" for missing values; status as a pill with words (plus the phase for active
 * rows), never colour alone; the table has a caption and header scopes and scrolls sideways in a
 * focusable labelled region with a sticky Process column; a click elsewhere on a row also opens
 * it (mouse convenience; the row is not focusable). Must not: delete or edit from a row.
 * A seeded evaluation session carries a "Simulated" tag next to its name (spec 24 §3.12).
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.141).
 */
import type { Ref } from 'react'
import { Pill } from '../ui/Pill'
import { Button } from '../ui/Button'
import { formatRelativeTime, phaseLabel } from '../../utils/discoveryFormat'
import { formatDate, formatDateTime, orDash, statusWord, STATUS_TONES } from '../../utils/workspaceFormat'
import type { ReviewListOut, ReviewRow } from '../../types/workspace'

const TH = 'border-b border-line-strong bg-surface-muted px-2 py-2 text-left align-bottom font-semibold text-fg whitespace-nowrap'
const TD = 'border-b border-line px-2 py-2 align-top text-fg'
const COLUMNS = ['Process', 'Status', 'Department', 'Cluster', 'Region', 'Fields', 'Steps', 'Messages', 'Documents', 'Updated', 'Created']

const n = (value: number) => value.toLocaleString('en-GB')

/** "<total> sessions · <active> in progress · …", the filter match and the truncation note. */
export function CountsLine({ data, filtered }: { data: ReviewListOut; filtered: boolean }) {
  const c = data.counts
  return (
    <p role="status" aria-live="polite" className="text-sm text-muted">
      {n(c.total)} sessions · {n(c.active)} in progress · {n(c.finished)} mapped · {n(c.noCandidate)} ended with nothing to map
      {filtered && ` · ${n(data.matching)} match the filters`}
      {data.truncated && <span className="block">Showing the 1,000 most recently updated sessions.</span>}
    </p>
  )
}

function Row({ row, striped, onOpen }: { row: ReviewRow; striped: boolean; onOpen: (row: ReviewRow) => void }) {
  const name = row.processName ?? 'Not named yet'
  return (
    <tr onClick={() => onOpen(row)} className={`cursor-pointer hover:bg-primary-soft ${striped ? 'bg-surface-muted' : 'bg-surface'}`}>
      <td className={`${TD} sticky left-0 z-10 bg-inherit`}>
        <button
          type="button"
          aria-label={`Open session ${row.processName ?? row.id}`}
          data-row-id={row.id}
          onClick={(e) => {
            e.stopPropagation()
            onOpen(row)
          }}
          className={`rounded text-left font-medium hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary ${
            row.processName ? 'text-link' : 'text-muted'
          }`}
        >
          {name}
        </button>
        {row.simulated && (
          <span className="ml-1.5">
            <Pill tone="info">Simulated</Pill>
          </span>
        )}
      </td>
      <td className={TD}>
        <Pill tone={STATUS_TONES[row.status] ?? 'neutral'}>{statusWord(row.status)}</Pill>
        {row.status === 'active' && <span className="mt-0.5 block text-xs text-muted">{phaseLabel(row.phase)}</span>}
      </td>
      <td className={TD}>{orDash(row.department)}</td>
      <td className={`${TD} whitespace-nowrap`}>{row.clusterCode ? `${row.clusterCode} · ${row.clusterName ?? ''}` : '—'}</td>
      <td className={TD}>{orDash(row.region)}</td>
      <td className={`${TD} whitespace-nowrap`}>
        {row.fieldsFilled} / {row.fieldsTotal}
      </td>
      <td className={TD}>{row.steps}</td>
      <td className={TD}>{row.messageCount}</td>
      <td className={TD}>{row.documentCount}</td>
      <td className={`${TD} whitespace-nowrap`}>
        <time dateTime={row.updatedAt} title={formatDateTime(row.updatedAt)}>
          {formatRelativeTime(row.updatedAt)}
        </time>
      </td>
      <td className={`${TD} whitespace-nowrap`}>
        <time dateTime={row.createdAt}>{formatDate(row.createdAt)}</time>
      </td>
    </tr>
  )
}

export function SessionTable({
  data,
  busy,
  onOpen,
  onClearFilters,
  regionRef,
}: {
  data: ReviewListOut
  busy: boolean
  onOpen: (row: ReviewRow) => void
  onClearFilters: () => void
  regionRef?: Ref<HTMLDivElement>
}) {
  if (data.counts.total === 0) return <p className="py-10 text-center text-sm text-muted">No discovery sessions yet.</p>
  if (data.rows.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 py-10 text-sm text-muted">
        <p>No sessions match these filters.</p>
        <Button onClick={onClearFilters}>Clear filters</Button>
      </div>
    )
  }
  return (
    <div
      ref={regionRef}
      role="region"
      aria-label="Session list"
      tabIndex={0}
      className="overflow-x-auto rounded-md border border-line focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
    >
      <table aria-busy={busy} className="w-full border-collapse text-sm">
        <caption className="px-2 py-1.5 text-left text-xs text-muted">Discovery sessions, newest update first</caption>
        <thead>
          <tr>
            {COLUMNS.map((c, i) => (
              <th key={c} scope="col" className={`${TH} ${i === 0 ? 'sticky left-0 z-10' : ''}`}>
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row, i) => (
            <Row key={row.id} row={row} striped={i % 2 === 1} onOpen={onOpen} />
          ))}
        </tbody>
      </table>
    </div>
  )
}
