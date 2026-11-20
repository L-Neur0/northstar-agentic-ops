/**
 * The look of the eight field statuses: a lucide icon, a word and a token colour (spec 23 §3.8.3).
 * Why: the interview panel and the workspace step grid (part 3, §19.4 block 2) must show a status
 * the same way, with an icon and a word, never by colour alone.
 * Rules: one entry per server status; unknown statuses fall back to `empty` at the caller.
 * Must not: decide a status; the server sends it.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57).
 */
import {
  AlertTriangle,
  CheckCircle2,
  Circle,
  CircleDashed,
  CircleSlash,
  Clock,
  FileText,
  MinusCircle,
  type LucideIcon,
} from 'lucide-react'
import type { FieldStatus } from '../../types/process-discovery'

/** Icon, word and colour per field status (also used by the workspace step grid, part 3). */
export const STATUS: Record<FieldStatus, { Icon: LucideIcon; label: string; colour: string }> = {
  complete: { Icon: CheckCircle2, label: 'Complete', colour: 'text-success' },
  partial: { Icon: CircleDashed, label: 'Partly answered', colour: 'text-warning' },
  invalid: { Icon: AlertTriangle, label: 'Needs a fix', colour: 'text-danger' },
  proposed: { Icon: FileText, label: 'Proposed', colour: 'text-link' },
  skipped: { Icon: MinusCircle, label: 'Skipped', colour: 'text-subtle' },
  deferred: { Icon: Clock, label: 'Asked again later', colour: 'text-warning' },
  given_up: { Icon: CircleSlash, label: 'Left open', colour: 'text-subtle' },
  empty: { Icon: Circle, label: 'Not answered yet', colour: 'text-line-strong' },
}
