/**
 * "How this works": the first-visit introduction of the interview (spec 23 §3.9; AC-23.44).
 * Why: the intro: five stages, each labelled with the phase-meter rungs it
 * covers so the words match the strip, the four *Finish* conditions, and one line on documents.
 * Rules: reopened from the header; **Got it, let's start** closes it (the page sets the flag).
 * Must not mention a go / no-go: the tool guides, it does not judge.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57).
 */
import { useRef } from 'react'
import { Search } from 'lucide-react'
import { Modal } from '../ui/Modal'
import { Button } from '../ui/Button'
import { PHASE_LABELS, type Phase } from '../../types/process-discovery'

const STAGES: Array<{ title: string; body: string; phases: Phase[] }> = [
  {
    title: 'About you and your work',
    body: 'A few questions about your department and role, then we look at your routine together and pick one process worth mapping.',
    phases: ['context', 'find'],
  },
  {
    title: 'Describe the process',
    body: 'What starts it, what it delivers, who uses the result, how often it runs, how long it takes today, and how many main steps it has.',
    phases: ['boundaries', 'measure', 'step_count'],
  },
  {
    title: 'Walk the steps',
    body: 'One step at a time: its goal, activities, the people and systems involved, the effort, where it hurts, approvals and exceptions.',
    phases: ['steps'],
  },
  {
    title: 'Confirm and finish',
    body: 'Confirm the roles and systems collected from your steps, fill any gaps, and press Finish once all four conditions below are met.',
    phases: ['confirm', 'review'],
  },
  {
    title: 'Your discovery report',
    body: 'You get the mapped process and an assessment of where AI could help, with hours, value and what to prepare first.',
    phases: ['finished'],
  },
]

const CONDITIONS = [
  'Your map is at least 80 % complete (the bar at the top turns green)',
  'Every step is described',
  'The roles involved are confirmed',
  'The systems involved are confirmed',
]

export function DiscoveryIntroModal({ onDismiss }: { onDismiss: () => void }) {
  const start = useRef<HTMLButtonElement>(null)
  return (
    <Modal
      title="Process Discovery"
      icon={<Search className="h-5 w-5 text-link" aria-hidden="true" />}
      onClose={onDismiss}
      initialFocusRef={start}
      size="lg"
      description="Map one process from your work in a 15 to 20 minute conversation and get a discovery report. The questions come from an AI assistant; you have the last word on every answer."
      footer={
        <Button ref={start} variant="primary" onClick={onDismiss}>
          Got it, let&apos;s start
        </Button>
      }
    >
      <ol className="flex flex-col gap-4">
        {STAGES.map((stage, i) => (
          <li key={stage.title}>
            <h3 className="text-sm font-semibold text-fg">
              {i + 1}. {stage.title}
            </h3>
            <p className="text-sm text-muted">{stage.body}</p>
            {stage.title === 'Confirm and finish' && (
              <ul aria-label="Finish conditions" className="mt-1 list-disc pl-5 text-sm text-muted">
                {CONDITIONS.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            )}
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {stage.phases.map((p) => (
                <span key={p} className="rounded border border-line bg-page px-2 py-0.5 text-xs text-muted">
                  {PHASE_LABELS[p]}
                </span>
              ))}
            </div>
          </li>
        ))}
      </ol>
      <p className="mt-4 text-sm text-muted">Documents can be added at any time; nothing from them counts until you confirm it.</p>
    </Modal>
  )
}
