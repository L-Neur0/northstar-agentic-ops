/**
 * Wire types of the workspace (admin) side: login, session list, read-only session view and
 * conversation (spec 23 §20; spec 21 §4.2; spec 16 §3.2).
 * Why: the workspace page, the HTTP client and the fake share one mirror of the server's camelCase
 * wire models, so a contract drift breaks the build instead of a screen.
 * Rules: names follow spec 21 §4.2 and the built `backend/app/models/workspace_wire.py` (Q14: the
 * server's names win), checked against the recorded `review-*.json` samples in
 * `services/contract.workspace.test.ts`. Grid cell values are display text made by the server
 * (Q15); the client never formats them.
 * Must not: hold logic, or add fields the server does not send.
 */
import type { FieldStatus, Message, Phase, SessionStatus } from './process-discovery'
import type { DiscoveryReport } from './report'

export type ReviewStatusFilter = 'active' | 'finished' | 'no_candidate'

export interface ReviewFilters {
  status: ReviewStatusFilter | null
  cluster: string | null
  q: string
}

export interface ReviewRow {
  id: string
  createdAt: string
  updatedAt: string
  processName: string | null
  department: string | null
  clusterCode: string | null
  clusterName: string | null
  region: string | null
  status: SessionStatus
  phase: Phase
  fieldsFilled: number
  fieldsTotal: number
  steps: number
  messageCount: number
  documentCount: number
  /** A seeded evaluation session (spec 24 §3.12): shown with a "Simulated" tag. */
  simulated: boolean
}

export interface ReviewCounts {
  total: number
  active: number
  finished: number
  noCandidate: number
}

export interface ReviewListOut {
  counts: ReviewCounts
  rows: ReviewRow[]
  matching: number
  truncated: boolean
}

export interface ReviewSummary {
  department: string | null
  function: string | null
  region: string | null
  processName: string | null
  clusterName: string | null
  status: SessionStatus
  phase: Phase
  fieldsFilled: number
  fieldsTotal: number
  stepsStarted: number
  stepsExpected: number
  /** The score value as a fraction 0–1 (shown as a whole percent). */
  completeness: number
  filledPoints: number
  totalPoints: number
  messageCount: number
  documentCount: number
}

export type CellSource = 'expert' | 'document' | 'specialist'

export interface GridCell {
  /** Display text made by the server (Q15); empty when not answered. */
  value: string
  source: CellSource | string | null
  status: FieldStatus | string | null
}

export interface GridRow {
  key: string
  id: string
  label: string
  /** One cell per step, in step order. */
  cells: GridCell[]
}

export interface StepGrid {
  stepNames: string[]
  rows: GridRow[]
}

export interface DocumentMeta {
  name: string
  kind: string
  /** Typed, never shown. */
  bytes: number
  uploadedAt: string
  outcome: 'read' | 'failed'
}

export interface ReviewSessionOut {
  id: string
  etag: string
  summary: ReviewSummary
  steps: StepGrid
  rawSteps: StepGrid | null
  documents: DocumentMeta[]
  report: DiscoveryReport | null
  simulated: boolean
}

export interface ConversationOut {
  sessionId: string
  messages: Message[]
}

export interface WorkspaceLogin {
  token: string
  role: 'specialist' | 'engineer'
  name: string
  expiresAt: string
}
