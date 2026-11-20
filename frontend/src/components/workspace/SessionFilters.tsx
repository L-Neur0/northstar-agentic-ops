/**
 * The filters of the workspace list: status, cluster, search (spec 23 §19.3; AC-23.120).
 * Why: the specialist narrows all discovery sessions to the ones they care about; the server
 * filters (spec 21 §3.2), so each change is one list call.
 * Rules: status and cluster apply at once; the search text is sent trimmed 300 ms after the last
 * key; **Clear filters** shows only when a filter is set and resets all three; the cluster select
 * lists the taxonomy as "<code> · <name>" and is disabled with only "All clusters" when the
 * taxonomy failed. Filters live in component state only. Must not: filter rows on the client.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.141).
 */
import { useEffect, useRef, useState } from 'react'
import { Button } from '../ui/Button'
import type { ClusterRef } from '../../types/process-discovery'
import type { ReviewFilters, ReviewStatusFilter } from '../../types/workspace'
import { NO_FILTERS } from '../../utils/workspaceFormat'
export const SEARCH_DEBOUNCE_MS = 300

const FIELD =
  'mt-1 block w-full rounded-md border border-line-strong bg-surface px-2 py-1.5 text-sm text-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary disabled:text-subtle'

export function SessionFilters({
  value,
  onChange,
  clusters,
  clustersFailed,
}: {
  value: ReviewFilters
  onChange: (next: ReviewFilters) => void
  clusters: ClusterRef[]
  clustersFailed: boolean
}) {
  const [text, setText] = useState(value.q)
  const latest = useRef({ value, onChange })
  useEffect(() => {
    latest.current = { value, onChange }
  })

  useEffect(() => {
    const q = text.trim()
    if (q === latest.current.value.q) return
    const timer = setTimeout(() => latest.current.onChange({ ...latest.current.value, q }), SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [text])

  const set = Boolean(value.status || value.cluster || value.q || text.trim())

  return (
    <section aria-label="Session filters" className="flex flex-wrap items-end gap-3">
      <label className="w-44 text-sm font-medium text-fg">
        Status
        <select
          value={value.status ?? ''}
          onChange={(e) => onChange({ ...value, status: (e.target.value || null) as ReviewStatusFilter | null })}
          className={FIELD}
        >
          <option value="">All statuses</option>
          <option value="active">In progress</option>
          <option value="finished">Mapped</option>
          <option value="no_candidate">Ended · nothing to map</option>
        </select>
      </label>
      <label className="w-56 text-sm font-medium text-fg">
        Cluster
        <select
          value={value.cluster ?? ''}
          disabled={clustersFailed}
          onChange={(e) => onChange({ ...value, cluster: e.target.value || null })}
          className={FIELD}
        >
          <option value="">All clusters</option>
          {!clustersFailed &&
            clusters.map((c) => (
              <option key={c.code} value={c.code}>
                {c.code} · {c.name}
              </option>
            ))}
        </select>
      </label>
      <label className="min-w-[12rem] flex-1 text-sm font-medium text-fg">
        Search
        <input
          type="search"
          maxLength={100}
          placeholder="Process, department or session id"
          value={text}
          onChange={(e) => setText(e.target.value)}
          className={FIELD}
        />
      </label>
      {set && (
        <Button
          onClick={() => {
            setText('')
            onChange(NO_FILTERS)
          }}
        >
          Clear filters
        </Button>
      )}
    </section>
  )
}
