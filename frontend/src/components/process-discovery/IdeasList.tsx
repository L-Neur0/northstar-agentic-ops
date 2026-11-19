/**
 * The ideas on My processes: processes the expert mentioned and can map later (spec 23 §3.3.7;
 * AC-23.11; F-03).
 * Why: during the find phase the agent keeps the candidates it did not map as ideas; each can be
 * started as a new session (its name is then proposed for P04) or deleted.
 * Rules: only `open` ideas are listed (a started idea shows as its session); the expert's words
 * are shown in quotes as they said them.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57).
 */
import { Lightbulb, Trash2 } from 'lucide-react'
import { Button } from '../ui/Button'
import type { Idea } from '../../types/process-discovery'

interface Props {
  ideas: Idea[]
  busyId: string | null
  onMap: (id: string) => void
  onDelete: (idea: Idea) => void
}

export function IdeasList({ ideas, busyId, onMap, onDelete }: Props) {
  const open = ideas.filter((i) => i.status === 'open')
  if (open.length === 0) {
    return <p className="text-sm text-subtle">No ideas yet. When you mention other processes during an interview, they are kept here.</p>
  }
  return (
    <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
      {open.map((idea) => (
        <li key={idea.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
          <Lightbulb className="h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-fg">{idea.name}</p>
            <p className="text-sm italic text-muted">&ldquo;{idea.words}&rdquo;</p>
          </div>
          <Button size="sm" variant="primary" loading={busyId === idea.id} disabled={busyId !== null} onClick={() => onMap(idea.id)}>
            Map this
          </Button>
          <Button size="sm" variant="tertiary" icon={<Trash2 className="h-3.5 w-3.5" aria-hidden="true" />} aria-label={`Delete idea ${idea.name}`} onClick={() => onDelete(idea)}>
            Delete
          </Button>
        </li>
      ))}
    </ul>
  )
}
