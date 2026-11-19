/**
 * Wire types of the interview side, a mirror of the backend's camelCase wire models (spec 15
 * part 2 §3.3–3.4, spec 12 §3.11) plus the few display constants every screen shares.
 * Why: one file that breaks the build when the contract changes, used alike by the real HTTP
 * client, the fake API and every component (spec 23 §4).
 * Rules: shapes follow spec 15 exactly; the profile keeps the registry's snake_case keys because
 * they are field addresses. Must not: hold profile logic, scores or completeness rules; the server
 * decides every status (product rule 2).
 */

export type Phase =
  | 'context'
  | 'find'
  | 'boundaries'
  | 'measure'
  | 'step_count'
  | 'steps'
  | 'confirm'
  | 'review'
  | 'finished'
  | 'no_candidate'

export type SessionStatus = 'active' | 'finished' | 'no_candidate'

export type FieldStatus =
  | 'complete'
  | 'partial'
  | 'invalid'
  | 'proposed'
  | 'skipped'
  | 'empty'
  | 'deferred'
  | 'given_up'

export type FinishBlock = 'below_gate' | 'substeps_incomplete' | 'roles_not_confirmed' | 'tools_not_confirmed'

export type ConfirmTarget = 'substeps' | 'roles' | 'tools'

export interface Message {
  id: string
  role: 'expert' | 'agent'
  text: string
  at: string
}

export interface FieldView {
  key: string
  id: string
  label: string
  phase: Phase
  status: FieldStatus
  reason: string
  missing: string[]
  source: 'expert' | 'document' | 'specialist' | null
  quote: string | null
  documentName: string | null
  asks: number
}

export interface FinishState {
  ready: boolean
  /** A known `FinishBlock`, or a code this client does not know yet (shown as is). */
  blockedBy: FinishBlock | string | null
  looksLikeTask: boolean
}

export interface Score {
  value: number
  filledPoints: number
  totalPoints: number
}

/* ---- Profile: registry keys of spec 12 §3.11, as stored (snake_case), no sidecars ---- */

export interface NoneRow {
  none: true
}
export interface RoleRow {
  role: string
  contribution: string
}
export interface ApprovalRow {
  approver_role: string
  waiting_time: string
}
export interface ExceptionRow {
  description: string
  loops_back_to: number | null
}
export interface SensitiveRow {
  item: string
  detail: string
}

export interface Step {
  name: string
  goal: string
  activities: string[]
  roles: Array<NoneRow | RoleRow>
  owner: string
  systems: string[]
  data: { inputs: string[]; outputs: string[] }
  effort: { duration: string; frequency: string }
  pain_points: string[]
  approvals: Array<NoneRow | ApprovalRow>
  exceptions: Array<NoneRow | ExceptionRow>
  handover: string
}

export interface ProcessProfile {
  name: string
  cluster: { code: string; name: string; decided_by: string }
  trigger: string
  end_result: string
  value_at_end: string
  business_pain: string
  volume: { count: number | null; period: string; raw: string }
  process_owner: { role: string; none_identified: boolean }
  baseline_metric: { value: string; unit: string; qualitative: string; estimated: boolean }
  target_metric: { value: string; unit: string }
  variation: { same: string; differences: string }
  sensitive_data: Array<NoneRow | SensitiveRow>
  substep_count: number | null
  substep_count_rejected: number | null
  substeps: Step[]
  all_roles: string[]
  all_tools: string[]
  substeps_complete: boolean
  roles_confirmed: boolean
  tools_confirmed: boolean
}

export interface Profile {
  department: string
  user_function: string
  region: string
  process: ProcessProfile
}

export interface ClusterRef {
  code: string
  name: string
  description: string
}

export interface SessionOut {
  id: string
  status: SessionStatus
  phase: Phase
  displayName: string | null
  createdAt: string
  updatedAt: string
  finishedAt: string | null
  messages: Message[]
  profile: Profile
  fieldViews: FieldView[]
  score: Score
  finish: FinishState
  scope: { verdict: string; widened: boolean } | null
  clusterProposal: ClusterRef | null
  reportStatus: 'mapped' | 'validated' | null
}

export interface TurnOut {
  reply: Message
  session: SessionOut
  ideasAdded: number
}

export interface SessionSummary {
  id: string
  status: SessionStatus
  phase: Phase
  processName: string | null
  clusterCode: string | null
  score: number
  messageCount: number
  createdAt: string
  updatedAt: string
  reportStatus: string | null
}

export interface Idea {
  id: string
  name: string
  words: string
  status: 'open' | 'started' | 'dismissed'
  fromSessionId: string
  startedSessionId: string | null
  createdAt: string
}

export interface ApiErrorBody {
  code: string
  message: string
  reason?: string
}

export interface Taxonomy {
  clusters: ClusterRef[]
}

export interface DeletedCounts {
  sessions: number
  ideas: number
}

/* ---- Display constants ---- */

/** The eight non-terminal phases in order (spec 12 §3.1 `PHASE_ORDER`). */
export const PHASE_ORDER: Phase[] = ['context', 'find', 'boundaries', 'measure', 'step_count', 'steps', 'confirm', 'review']

/** The rungs of the phase meter: `PHASE_ORDER`, then Finished (spec 23 §3.6.1). */
export const PHASE_STRIP: Phase[] = [...PHASE_ORDER, 'finished']

export const PHASE_LABELS: Record<Phase, string> = {
  context: 'About you',
  find: 'Process',
  boundaries: 'Boundaries',
  measure: 'Measures',
  step_count: 'Step count',
  steps: 'Steps',
  confirm: 'Confirm',
  review: 'Review',
  finished: 'Finished',
  no_candidate: 'Ended',
}

/** The five `ProcessCard` sections, keyed by the field view phase (spec 23 §3.8.2). */
export type ProcessSectionId = 'context' | 'find' | 'boundaries' | 'measure' | 'step_count'
export type PanelSectionId = ProcessSectionId | 'steps' | 'confirm'

export const PROCESS_SECTIONS: ProcessSectionId[] = ['context', 'find', 'boundaries', 'measure', 'step_count']

export const SECTION_OF_PHASE: Record<ProcessSectionId, string> = {
  context: 'About you',
  find: 'The process',
  boundaries: 'Boundaries',
  measure: 'Measures',
  step_count: 'Number of steps',
}

export const FINISH_BLOCKED_MESSAGES: Record<FinishBlock, (pct: number) => string> = {
  below_gate: (pct) => `Your map is ${pct} % complete. It needs 80 % to finish.`,
  substeps_incomplete: () => 'Some steps are not fully described yet.',
  roles_not_confirmed: () => 'Please confirm the list of roles.',
  tools_not_confirmed: () => 'Please confirm the list of systems.',
}

/** Message length limit (spec 15 route 5). */
export const MESSAGE_MAX_CHARS = 16000

/** S01–S11 leaves are scored; S12 (`handover`) is not (spec 12 §3.4). */
export const STEP_LEAVES = [
  'name',
  'goal',
  'activities',
  'roles',
  'owner',
  'systems',
  'data',
  'effort',
  'pain_points',
  'approvals',
  'exceptions',
  'handover',
] as const
export const UNSCORED_STEP_LEAVES = ['handover']
export const SCORED_CELLS_PER_STEP = 11
