/**
 * Wire types of the interview side, a mirror of the backend's camelCase wire models (spec 15
 * part 2 §3.3–3.4, spec 12 §3.11) plus the few display constants every screen shares.
 * Why: one file that breaks the build when the contract changes, used alike by the real HTTP
 * client, the fake API and every component (spec 23 §4).
 * Rules: shapes follow the backend's `models/process_discovery_wire.py` exactly (checked against
 * recorded responses in `services/contract.test.ts`); the profile keeps the registry's snake_case keys because
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
  /** Spec 13 §3.13 item 5: the value was read from an image (meta `fromImage`). */
  fromImage: boolean
  /** Spec 13 §3.13 item 5: an open or left conflict with a document on this field. */
  conflict: 'open' | 'left' | null
  /** Spec 17 §3.21 P4: one source per item when the value mixes sources (else empty). */
  items: FieldItemView[]
}

/** The source of one item of a value read from several files (spec 17 §3.21 P2–P4). */
export interface FieldItemView {
  sub: string | null
  item: string | null
  source: 'expert' | 'document' | 'specialist' | null
  documentName: string | null
  fromImage: boolean
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
  /** The session's documents, counts only (spec 17 §3.13). Every recorded response carries it. */
  documents: DocumentOut[]
}

/* ---- Documents (spec 17; spec 23 part 2 §12) ---- */

/** One uploaded document as the panel lists it; `bytes` and `chars` are typed but never shown. */
export interface DocumentOut {
  id: string
  name: string
  kind: string
  bytes: number
  chars: number
  truncated: boolean
  uploadedAt: string
  outcome: 'read' | 'failed'
  proposals: number
  pending: number
}

export interface Tally {
  fields: number
  steps: number
  cells: number
}

export interface DocumentReportOut {
  documentId: string
  outcome: 'read' | 'failed'
  reader: 'model' | 'bpmn'
  truncated: boolean
  offered: Tally
  kept: Tally
  dropped: number
  skipped: { key: string; reason: string; items: number | null }[]
  stepList: number
  /** The spec 17 §3.12 sentence the expert is told. */
  message: string
  /** Spec 17 §3.18: what the file is relative to the interview, and the step it was read for. */
  documentRole: string | null
  targetStep: number | null
  targetSource: 'document' | 'expert' | 'focus' | 'none'
  fromImage: boolean
  /** Spec 17 §3.21 item 6: conflicts the reading recorded (asked in the chat). */
  conflicts: number
}

export interface DocumentUploadOut {
  session: SessionOut
  document: DocumentOut
  report: DocumentReportOut
  /** The agent's question about the file (spec 14 §3.16); also the last entry of `session.messages`. */
  reply: Message
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

/**
 * Every `code` the interview API sends (backend `api/errors.py`, `core/access.py`, the routes), plus
 * the client's own `network` and `http_<status>`. `reason` comes only with `map_incomplete`.
 */
export type ApiErrorCode =
  | 'session_closed' // 400
  | 'unsafe_input' // 400
  | 'visitor_key_required' // 401
  | 'not_found' // 404
  | 'map_incomplete' // 409, with reason
  | 'conflict' // 409
  | 'idea_started' // 409
  | 'unknown_cluster' // 422
  | 'invalid_value' // 422, request validation
  | 'rate_limited' // 429
  | 'budget_exhausted' // 429
  | 'internal_error' // 500
  | 'model_unavailable' // 503
  | 'store_unavailable' // 503
  | 'network' // 0, client side
  | 'document_limit' // 409, upload
  | 'document_too_large' // 413, upload
  | 'document_type' // 415, upload
  | 'document_unreadable' // 422, upload
  | 'report_not_ready' // 409, report before Finish
  | 'workspace_code_invalid' // 401, workspace login (spec 16)
  | 'workspace_code_required' // 401, workspace call without a valid token
  | 'forbidden' // 403, workspace token of another role
  | 'etag_required' // 428, workspace delete without If-Match (spec 21)

export interface ApiErrorBody {
  /** An `ApiErrorCode`, or a code this client does not know yet (its message is shown). */
  code: ApiErrorCode | string
  message: string
  reason?: string
}

export interface Taxonomy {
  clusters: ClusterRef[]
}

/** `GET /api/config`: public runtime values; part 2 reads the document limits (spec 23 §11.3). */
export interface PublicConfig {
  productName: string
  regions: string[]
  languages: string[]
  documents: { allowedTypes: string[]; maxFiles: number; maxFileMb: number; maxImageMb: number }
  /** Open demo workspace: name-only login, delete switched off (spec 16 §3.2 item 5). */
  workspaceOpen: boolean
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
export type PanelSectionId = ProcessSectionId | 'steps' | 'confirm' | 'documents'

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

/** Extension or kind → the word the panel shows (spec 23 §11.3.2); unknown ones show upper case. */
export const DOCUMENT_KIND_WORDS: Record<string, string> = {
  pdf: 'PDF',
  docx: 'Word',
  xlsx: 'Excel',
  csv: 'CSV',
  txt: 'text',
  md: 'Markdown',
  pptx: 'PowerPoint',
  eml: 'e-mail (.eml)',
  bpmn: 'BPMN',
  xml: 'BPMN',
  png: 'PNG',
  jpg: 'JPG',
  jpeg: 'JPG',
}

/** Document kinds that are images: their proposals are shown "(from an image)" (spec 17 §3.19 I5). */
export const IMAGE_KINDS: readonly string[] = ['png', 'jpeg']

/** The spec 17 §3.12 refusal sentences; `<max>` is filled from the config. */
export const DOCUMENT_ERROR_SENTENCES = {
  document_limit: 'You can add up to <max> documents. Remove one to add another.',
  document_too_large: 'This file is larger than <max> MB.',
  document_type: "This file type can't be read. Use PDF, Word, Excel, CSV, text, Markdown or BPMN.",
  document_unreadable: "I couldn't find any text in this file. If it is a scan, try the file it was made from.",
  unsafe_input: "This document contains text that looks like instructions to the assistant, so I didn't read it.",
  invalid_value: 'That file could not be sent. Please try again.',
} as const
