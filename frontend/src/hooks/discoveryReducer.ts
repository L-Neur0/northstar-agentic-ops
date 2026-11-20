/**
 * The interview page reducer (spec 23 §3.10, §11.9; AC-23.43, AC-23.66, AC-23.80).
 * Why: one reducer holds the page state; with spec 15
 * every write returns the full `SessionOut`, so the rule here is simple: a response replaces the
 * server slice (`session`) and never touches the UI slice (dialogs, banner, composer text).
 * Rules: every async result carries the session id it was started for (`forId`); a result for
 * another session is ignored, so a slow reply after **New** cannot overwrite the new session.
 * Part 2 adds the document writes (upload with progress, removal, ✓ / ✎) and their notices; only
 * one write runs at a time (`isWriting`), so two writes never race on one session.
 * Must not: compute scores, phases or finish state, or count proposals; those come from the server.
 */
import type { ConfirmTarget, DocumentUploadOut, Message, SessionOut, SessionSummary, TurnOut } from '../types/process-discovery'

export type PendingKind = 'confirming' | 'settingCluster' | 'closing' | 'finishing' | 'uploading' | 'removingDocument' | 'proposals'

export interface Uploading {
  name: string
  percent: number | null
  stage: 'sending' | 'reading'
}

export interface Pending {
  sending: boolean
  confirming: ConfirmTarget | null
  settingCluster: boolean
  closing: boolean
  finishing: boolean
  uploading: Uploading | null
  removingDocument: string | null
  proposals: { keys: string[]; kind: 'confirm' | 'reject' } | null
}

/** True while a document write (upload, removal, ✓ / ✎) is in flight (spec 23 §11.4.3). */
export function isWriting(pending: Pending): boolean {
  return pending.uploading !== null || pending.removingDocument !== null || pending.proposals !== null
}

export interface DiscoveryState {
  sessionId: string | null
  session: SessionOut | null
  optimistic: Message | null
  pending: Pending
  locked: boolean
  ideasAdded: number
  restoreText: string | null
  clusterPickerOpen: boolean
  clusterError: string | null
  error: string | null
  initFailed: boolean
  loading: boolean
  pastSessions: SessionSummary[]
  sessionsModalMode: 'welcome' | 'browse' | null
  /** The last upload's result sentence (`report.message`). */
  documentNotice: string | null
  /** The Documents panel's inline error sentence. */
  documentError: string | null
  /** "Removed. The agent will ask you about <label>." until the next send. */
  proposalNotice: string | null
}

const NO_PENDING: Pending = {
  sending: false,
  confirming: null,
  settingCluster: false,
  closing: false,
  finishing: false,
  uploading: null,
  removingDocument: null,
  proposals: null,
}

export const initialDiscoveryState: DiscoveryState = {
  sessionId: null,
  session: null,
  optimistic: null,
  pending: NO_PENDING,
  locked: false,
  ideasAdded: 0,
  restoreText: null,
  clusterPickerOpen: false,
  clusterError: null,
  error: null,
  initFailed: false,
  loading: false,
  pastSessions: [],
  sessionsModalMode: null,
  documentNotice: null,
  documentError: null,
  proposalNotice: null,
}

export type DiscoveryAction =
  | { type: 'BOOT_STARTED'; sessionId: string | null }
  | { type: 'SESSION_RECEIVED'; forId: string | null; session: SessionOut; kind?: PendingKind; notice?: string }
  | { type: 'MESSAGE_SENDING'; forId: string; message: Message }
  | { type: 'TURN_RECEIVED'; forId: string; turn: TurnOut }
  | { type: 'TURN_FAILED'; forId: string; text: string; message: string | null; lock: boolean }
  | { type: 'ACTION_STARTED'; forId: string; kind: PendingKind; target?: ConfirmTarget }
  | { type: 'ACTION_FAILED'; forId: string; kind: PendingKind; message: string; where: 'banner' | 'picker' | 'documents' }
  | { type: 'FINISH_BLOCKED'; forId: string; reason: string }
  | { type: 'SESSION_LOCKED'; forId: string }
  | { type: 'CLUSTER_PICKER_OPENED' }
  | { type: 'CLUSTER_PICKER_CLOSED' }
  | { type: 'SESSIONS_SHOWN'; list: SessionSummary[]; mode: 'welcome' | 'browse' }
  | { type: 'SESSIONS_HIDDEN' }
  | { type: 'ERROR'; message: string }
  | { type: 'ERROR_CLEARED' }
  | { type: 'INIT_FAILED'; message: string }
  | { type: 'RESTORE_CONSUMED' }
  | { type: 'UPLOAD_STARTED'; forId: string; name: string }
  | { type: 'UPLOAD_PROGRESS'; forId: string; percent: number }
  | { type: 'DOCUMENT_UPLOADED'; forId: string; upload: DocumentUploadOut }
  | { type: 'DOCUMENT_REJECTED'; forId: string; message: string }
  | { type: 'DOCUMENT_REMOVING'; forId: string; docId: string }
  | { type: 'PROPOSALS_STARTED'; forId: string; keys: string[]; kind: 'confirm' | 'reject' }
  | { type: 'DOCUMENT_NOTICE_CLEARED' }
  | { type: 'DOCUMENT_ERROR_CLEARED' }

const NULL_FLAGS: PendingKind[] = ['confirming', 'uploading', 'removingDocument', 'proposals']

function clearFlag(pending: Pending, kind: PendingKind): Pending {
  return { ...pending, [kind]: NULL_FLAGS.includes(kind) ? null : false }
}

export function discoveryReducer(state: DiscoveryState, action: DiscoveryAction): DiscoveryState {
  if ('forId' in action && action.forId !== state.sessionId) return state

  switch (action.type) {
    case 'BOOT_STARTED':
      return { ...initialDiscoveryState, sessionId: action.sessionId, loading: true }
    case 'SESSION_RECEIVED':
      return {
        ...state,
        sessionId: action.session.id,
        session: action.session,
        loading: false,
        optimistic: null,
        pending: action.kind ? clearFlag(state.pending, action.kind) : state.pending,
        clusterPickerOpen: action.kind === 'settingCluster' ? false : state.clusterPickerOpen,
        clusterError: action.kind === 'settingCluster' ? null : state.clusterError,
        proposalNotice: action.notice ?? state.proposalNotice,
      }
    case 'MESSAGE_SENDING':
      return {
        ...state,
        optimistic: action.message,
        pending: { ...state.pending, sending: true },
        ideasAdded: 0,
        proposalNotice: null,
      }
    case 'TURN_RECEIVED':
      return {
        ...state,
        session: action.turn.session,
        optimistic: null,
        pending: { ...state.pending, sending: false },
        ideasAdded: action.turn.ideasAdded,
      }
    case 'TURN_FAILED':
      return {
        ...state,
        optimistic: null,
        restoreText: action.text,
        pending: action.lock ? NO_PENDING : { ...state.pending, sending: false },
        locked: action.lock ? true : state.locked,
        error: action.lock ? state.error : action.message,
      }
    case 'ACTION_STARTED':
      return {
        ...state,
        pending: { ...state.pending, [action.kind]: action.kind === 'confirming' ? (action.target ?? null) : true },
        clusterError: action.kind === 'settingCluster' ? null : state.clusterError,
      }
    case 'ACTION_FAILED':
      return {
        ...state,
        pending: clearFlag(state.pending, action.kind),
        error: action.where === 'banner' ? action.message : state.error,
        clusterError: action.where === 'picker' ? action.message : state.clusterError,
        documentError: action.where === 'documents' ? action.message : state.documentError,
      }
    case 'FINISH_BLOCKED':
      return state.session
        ? {
            ...state,
            session: { ...state.session, finish: { ...state.session.finish, ready: false, blockedBy: action.reason } },
            pending: clearFlag(state.pending, 'finishing'),
          }
        : state
    case 'SESSION_LOCKED':
      return { ...state, locked: true, pending: NO_PENDING }
    case 'CLUSTER_PICKER_OPENED':
      return { ...state, clusterPickerOpen: true, clusterError: null }
    case 'CLUSTER_PICKER_CLOSED':
      return { ...state, clusterPickerOpen: false, clusterError: null }
    case 'SESSIONS_SHOWN':
      return { ...state, pastSessions: action.list, sessionsModalMode: action.mode, loading: false }
    case 'SESSIONS_HIDDEN':
      return { ...state, sessionsModalMode: null }
    case 'ERROR':
      return { ...state, error: action.message }
    case 'ERROR_CLEARED':
      return { ...state, error: null }
    case 'INIT_FAILED':
      return { ...state, initFailed: true, loading: false, error: action.message }
    case 'RESTORE_CONSUMED':
      return { ...state, restoreText: null }
    case 'UPLOAD_STARTED':
      return {
        ...state,
        pending: { ...state.pending, uploading: { name: action.name, percent: 0, stage: 'sending' } },
        documentNotice: null,
        documentError: null,
      }
    case 'UPLOAD_PROGRESS': {
      const up = state.pending.uploading
      if (!up) return state
      const next: Uploading = action.percent >= 100 ? { ...up, percent: null, stage: 'reading' } : { ...up, percent: action.percent }
      return { ...state, pending: { ...state.pending, uploading: next } }
    }
    case 'DOCUMENT_UPLOADED':
      return {
        ...state,
        session: action.upload.session,
        documentNotice: action.upload.report.message,
        pending: { ...state.pending, uploading: null },
      }
    case 'DOCUMENT_REJECTED':
      return { ...state, documentError: action.message, documentNotice: null, pending: { ...state.pending, uploading: null } }
    case 'DOCUMENT_REMOVING':
      return { ...state, pending: { ...state.pending, removingDocument: action.docId } }
    case 'PROPOSALS_STARTED':
      return { ...state, pending: { ...state.pending, proposals: { keys: action.keys, kind: action.kind } } }
    case 'DOCUMENT_NOTICE_CLEARED':
      return { ...state, documentNotice: null }
    case 'DOCUMENT_ERROR_CLEARED':
      return { ...state, documentError: null }
  }
}
