/**
 * The sessions dialog of the interview page (spec 23 §3.9; AC-23.45).
 * Why: the sessions modal. **Welcome** mode opens at boot when unfinished
 * sessions exist and forces a choice (no close button, Escape and backdrop ignored); **browse**
 * mode opens from "Past sessions" and closes normally.
 * Rules: each card shows the name (or "Not named yet"), a pill with words ("Finished", "Ended" or
 * the percentage), the phase label and a relative time; the caller decides where a card leads.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57).
 */
import { Clock, Search } from 'lucide-react'
import { Modal } from '../ui/Modal'
import { Button } from '../ui/Button'
import { Pill, type PillTone } from '../ui/Pill'
import { completenessPct, formatRelativeTime, phaseLabel } from '../../utils/discoveryFormat'
import type { SessionSummary } from '../../types/process-discovery'

function pill(s: SessionSummary): { tone: PillTone; text: string } {
  if (s.status === 'finished') return { tone: 'success', text: 'Finished' }
  if (s.status === 'no_candidate') return { tone: 'neutral', text: 'Ended' }
  const pct = completenessPct(s.score)
  return { tone: pct >= 80 ? 'success' : pct >= 30 ? 'warning' : 'danger', text: `${pct} %` }
}

interface Props {
  mode: 'welcome' | 'browse'
  sessions: SessionSummary[]
  onOpen: (session: SessionSummary) => void
  onStartNew: () => void
  onClose: () => void
}

export function DiscoverySessionsModal({ mode, sessions, onOpen, onStartNew, onClose }: Props) {
  const welcome = mode === 'welcome'
  const intro = welcome
    ? sessions.length === 1
      ? 'You have a session in progress. Continue where you left off?'
      : 'You have sessions in progress. Continue one or start a new one.'
    : sessions.length === 0
      ? 'You have no sessions yet.'
      : 'Choose a session to open.'

  return (
    <Modal
      title={welcome ? 'Welcome back' : 'Past sessions'}
      icon={<Search className="h-5 w-5 text-link" aria-hidden="true" />}
      onClose={onClose}
      dismissible={!welcome}
      description={intro}
      footer={
        <Button className="w-full" onClick={onStartNew}>
          Start new session
        </Button>
      }
    >
      <ul className="flex flex-col gap-2">
        {sessions.map((s) => {
          const { tone, text } = pill(s)
          return (
            <li key={s.id}>
              <button
                type="button"
                onClick={() => onOpen(s)}
                className="w-full rounded-lg border border-line bg-surface px-4 py-3 text-left hover:border-primary hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
              >
                <span className="block truncate text-sm font-medium text-fg">{s.processName || 'Not named yet'}</span>
                <span className="mt-1 flex items-center justify-between gap-2 text-xs text-subtle">
                  <span className="flex items-center gap-2">
                    <Pill tone={tone}>{text}</Pill>
                    {phaseLabel(s.phase)}
                  </span>
                  <span className="flex items-center gap-1">
                    <Clock className="h-3 w-3" aria-hidden="true" />
                    {formatRelativeTime(s.updatedAt)}
                  </span>
                </span>
              </button>
            </li>
          )
        })}
      </ul>
    </Modal>
  )
}
