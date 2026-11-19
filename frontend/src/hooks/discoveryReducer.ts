/**
 * The interview page reducer (spec 23 §3.10; AC-23.43).
 * Why: one reducer holds the page state; with spec 15
 * every write returns the full `SessionOut`, so the rule here is simple: a response replaces the
 * server slice (`session`) and never touches the UI slice (dialogs, banner, composer text).
 * Rules: every async result carries the session id it was started for (`forId`); a result for
 * another session is ignored, so a slow reply after **New** cannot overwrite the new session.
 * Must not: compute scores, phases or finish state; those come from the server.
 */
import type { ConfirmTarget, Message, SessionOut, SessionSummary, TurnOut } from '../types/process-discovery'

export type PendingKind = 'confirming' | 'settingCluster' | 'closing' | 'finishing'

export interface Pending {
  sending: boolean
  confirming: ConfirmTarget | null
  settingCluster: boolean
  closing: boolean
  finishing: boolean
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
}

const NO_PENDING: Pending = { sending: false, confirming: null, settingCluster: false, closing: false, finishing: false }

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
}

export type DiscoveryAction =
  | { type: 'BOOT_STARTED'; sessionId: string | null }
  | { type: 'SESSION_RECEIVED'; forId: string | null; session: SessionOut; kind?: PendingKind }
  | { type: 'MESSAGE_SENDING'; forId: string; message: Message }
  | { type: 'TURN_RECEIVED'; forId: string; turn: TurnOut }
  | { type: 'TURN_FAILED'; forId: string; text: string; message: string | null; lock: boolean }
  | { type: 'ACTION_STARTED'; forId: string; kind: PendingKind; target?: ConfirmTarget }
  | { type: 'ACTION_FAILED'; forId: string; kind: PendingKind; message: string; where: 'banner' | 'picker' }
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

function clearFlag(pending: Pending, kind: PendingKind): Pending {
  return { ...pending, [kind]: kind === 'confirming' ? null : false }
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
      }
    case 'MESSAGE_SENDING':
      return { ...state, optimistic: action.message, pending: { ...state.pending, sending: true }, ideasAdded: 0 }
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
  }
}
