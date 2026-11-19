/**
 * Dialog to pick the process cluster (P05) from the company taxonomy (spec 23 §3.9; AC-23.36,
 * AC-23.37; F-07).
 * Why: lets the expert pick a cluster. The clusters are company configuration served by
 * `GET /api/taxonomy`, shown in file order as "<name> (<code>)" with the plain description.
 * Rules: the current cluster is `aria-pressed="true"`; while the save is in flight the dialog stays
 * open, every button is disabled and Escape is ignored; the parent closes it only on success and
 * passes the 422 `unknown_cluster` message back as `error`. Must not save anything itself.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57).
 */
import { useQuery } from '@tanstack/react-query'
import { Modal } from '../ui/Modal'
import { Button } from '../ui/Button'
import { Spinner } from '../ui/Spinner'
import { useApi } from '../../services/apiContext'

interface Props {
  currentCode: string
  saving: boolean
  error: string | null
  onSelect: (code: string) => void
  onClose: () => void
}

export function ClusterPicker({ currentCode, saving, error, onSelect, onClose }: Props) {
  const api = useApi()
  const taxonomy = useQuery({ queryKey: ['taxonomy'], queryFn: () => api.getTaxonomy(), staleTime: Infinity })

  return (
    <Modal
      title="Pick a cluster"
      onClose={onClose}
      dismissible={!saving}
      size="lg"
      description="Which part of the company does this process belong to?"
      footer={
        <Button onClick={onClose} disabled={saving}>
          Cancel
        </Button>
      }
    >
      {error && (
        <p role="alert" className="mb-3 rounded border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}
      {taxonomy.isPending && (
        <p role="status" className="flex items-center gap-2 py-4 text-sm text-muted">
          <Spinner size="sm" /> Loading the clusters…
        </p>
      )}
      {taxonomy.isError && (
        <div role="alert" className="flex items-center gap-3 py-4 text-sm text-danger">
          <span>We could not load the clusters.</span>
          <Button size="sm" onClick={() => void taxonomy.refetch()}>
            Retry
          </Button>
        </div>
      )}
      {taxonomy.data && (
        <ul className="flex flex-col gap-1.5">
          {taxonomy.data.clusters.map((c) => {
            const selected = c.code === currentCode
            return (
              <li key={c.code}>
                <button
                  type="button"
                  aria-pressed={selected}
                  disabled={saving}
                  onClick={() => onSelect(c.code)}
                  className={`w-full rounded-lg border px-3 py-2 text-left hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary disabled:cursor-progress disabled:opacity-70 ${
                    selected ? 'border-primary ring-1 ring-primary' : 'border-line'
                  }`}
                >
                  <span className="text-sm font-semibold text-fg">
                    {c.name} <span className="font-normal text-subtle">({c.code})</span>
                  </span>
                  {selected && <span className="ml-2 text-xs text-link">Selected</span>}
                  <span className="mt-0.5 block text-sm text-muted">{c.description}</span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
      {saving && (
        <p role="status" className="mt-2 flex items-center gap-2 text-sm text-muted">
          <Spinner size="sm" /> Saving…
        </p>
      )}
    </Modal>
  )
}
