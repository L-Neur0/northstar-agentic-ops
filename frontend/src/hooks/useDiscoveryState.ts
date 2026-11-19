/**
 * State and actions of the interview page (spec 23 §3.5, §3.7, §3.10, §3.11; AC-23.14–23.16,
 * AC-23.21–23.23, AC-23.40, AC-23.41).
 * Why: the page's reducer and handlers. One reducer holds the server slice;
 * this hook runs the boot flow (open a session, or offer the welcome dialog, or create one) and
 * every write, and routes each failure through the error table of `discoveryErrors`.
 * Rules: the boot runs once per URL, also under StrictMode (a ref fence); a create navigates with
 * `replace` and does not GET again; every result carries the session id it was started for, so a
 * late reply for another session is ignored; 409 `map_incomplete` is not an error; 409 `conflict`
 * reloads the session; 400 `session_closed` locks the composer. Must not compute any profile logic.
 */
import { useCallback, useEffect, useReducer, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useApi } from '../services/apiContext'
import { discoveryReducer, initialDiscoveryState, type PendingKind } from './discoveryReducer'
import { errorEffect, errorText } from '../utils/discoveryErrors'
import { displayNameForCreate } from '../access/displayName'
import type { ConfirmTarget, Message, SessionOut } from '../types/process-discovery'

function tempId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `tmp-${Date.now()}-${Math.random()}`
}

export function useDiscoveryState(urlSessionId?: string) {
  const api = useApi()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [state, dispatch] = useReducer(discoveryReducer, initialDiscoveryState)
  const stateRef = useRef(state)
  const bootedFor = useRef<string | null>(null)

  useEffect(() => {
    stateRef.current = state
  })

  const refreshLists = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ['sessions'] })
  }, [queryClient])

  const createNew = useCallback(async () => {
    dispatch({ type: 'BOOT_STARTED', sessionId: null })
    try {
      const session = await api.createSession({ displayName: displayNameForCreate() })
      bootedFor.current = session.id
      dispatch({ type: 'SESSION_RECEIVED', forId: null, session })
      refreshLists()
      navigate(`/process-discovery/${session.id}`, { replace: true })
    } catch (e) {
      dispatch({ type: 'INIT_FAILED', message: errorText(e) })
    }
  }, [api, navigate, refreshLists])

  const load = useCallback(
    async (id: string) => {
      dispatch({ type: 'BOOT_STARTED', sessionId: id })
      try {
        const session = await api.getSession(id)
        dispatch({ type: 'SESSION_RECEIVED', forId: id, session })
      } catch (e) {
        const effect = errorEffect(e, 'boot')
        dispatch({ type: 'INIT_FAILED', message: 'message' in effect ? effect.message : errorText(e) })
      }
    },
    [api],
  )

  const boot = useCallback(async () => {
    if (urlSessionId) {
      await load(urlSessionId)
      return
    }
    dispatch({ type: 'BOOT_STARTED', sessionId: null })
    try {
      const { sessions } = await api.listSessions()
      const active = sessions.filter((s) => s.status === 'active')
      if (active.length > 0) {
        dispatch({ type: 'SESSIONS_SHOWN', list: active, mode: 'welcome' })
        return
      }
    } catch {
      /* a failed list falls back to a new session */
    }
    await createNew()
  }, [api, createNew, load, urlSessionId])

  useEffect(() => {
    const key = urlSessionId ?? '/'
    if (bootedFor.current === key) return
    bootedFor.current = key
    void boot()
  }, [boot, urlSessionId])

  /** GET the session again after a 409 conflict; the banner stays. */
  const reload = useCallback(
    async (id: string) => {
      try {
        const session = await api.getSession(id)
        dispatch({ type: 'SESSION_RECEIVED', forId: id, session })
      } catch {
        /* the banner already explains */
      }
    },
    [api],
  )

  const sendMessage = useCallback(
    async (text: string) => {
      const s = stateRef.current
      if (!s.session || !s.sessionId || s.pending.sending) return
      const forId = s.sessionId
      const message: Message = { id: tempId(), role: 'expert', text, at: new Date().toISOString() }
      dispatch({ type: 'MESSAGE_SENDING', forId, message })
      try {
        const turn = await api.sendMessage(forId, text)
        dispatch({ type: 'TURN_RECEIVED', forId, turn })
        if (turn.ideasAdded > 0) void queryClient.invalidateQueries({ queryKey: ['ideas'] })
      } catch (e) {
        const effect = errorEffect(e, 'turn')
        const lock = effect.kind === 'lock'
        const msg = 'message' in effect ? effect.message : errorText(e)
        dispatch({ type: 'TURN_FAILED', forId, text, message: lock ? null : msg, lock })
        if (effect.kind === 'reload') void reload(forId)
      }
    },
    [api, queryClient, reload],
  )

  const runAction = useCallback(
    async (kind: PendingKind, call: (id: string) => Promise<SessionOut>, target?: ConfirmTarget): Promise<SessionOut | null> => {
      const forId = stateRef.current.sessionId
      if (!forId || !stateRef.current.session) return null
      dispatch({ type: 'ACTION_STARTED', forId, kind, target })
      try {
        const session = await call(forId)
        dispatch({ type: 'SESSION_RECEIVED', forId, session, kind })
        return session
      } catch (e) {
        const effect = errorEffect(e, kind === 'settingCluster' ? 'picker' : kind === 'finishing' ? 'finish' : 'action')
        switch (effect.kind) {
          case 'lock':
            dispatch({ type: 'SESSION_LOCKED', forId })
            break
          case 'finish_blocked':
            dispatch({ type: 'FINISH_BLOCKED', forId, reason: effect.reason })
            break
          case 'picker':
            dispatch({ type: 'ACTION_FAILED', forId, kind, message: effect.message, where: 'picker' })
            break
          case 'reload':
            dispatch({ type: 'ACTION_FAILED', forId, kind, message: effect.message, where: 'banner' })
            void reload(forId)
            break
          default:
            dispatch({ type: 'ACTION_FAILED', forId, kind, message: effect.message, where: 'banner' })
        }
        return null
      }
    },
    [reload],
  )

  const confirm = useCallback(
    (target: ConfirmTarget) => {
      if (stateRef.current.pending.confirming) return Promise.resolve(null)
      return runAction('confirming', (id) => api.confirm(id, target), target)
    },
    [api, runAction],
  )

  const setCluster = useCallback((code: string) => runAction('settingCluster', (id) => api.setCluster(id, code)), [api, runAction])

  const closeSession = useCallback(async () => {
    if (stateRef.current.pending.closing) return null
    const s = await runAction('closing', (id) => api.close(id))
    if (s) refreshLists()
    return s
  }, [api, refreshLists, runAction])

  const finish = useCallback(async () => {
    if (stateRef.current.pending.finishing) return null
    const s = await runAction('finishing', (id) => api.finish(id))
    if (s) {
      refreshLists()
      navigate(`/report/${s.id}`)
    }
    return s
  }, [api, navigate, refreshLists, runAction])

  const showPastSessions = useCallback(async () => {
    try {
      const { sessions } = await api.listSessions()
      dispatch({ type: 'SESSIONS_SHOWN', list: sessions, mode: 'browse' })
    } catch (e) {
      dispatch({ type: 'ERROR', message: errorText(e) })
    }
  }, [api])

  return {
    state,
    boot,
    createNew,
    sendMessage,
    confirm,
    setCluster,
    closeSession,
    finish,
    showPastSessions,
    hidePastSessions: useCallback(() => dispatch({ type: 'SESSIONS_HIDDEN' }), []),
    openPicker: useCallback(() => dispatch({ type: 'CLUSTER_PICKER_OPENED' }), []),
    closePicker: useCallback(() => dispatch({ type: 'CLUSTER_PICKER_CLOSED' }), []),
    clearError: useCallback(() => dispatch({ type: 'ERROR_CLEARED' }), []),
    restoreConsumed: useCallback(() => dispatch({ type: 'RESTORE_CONSUMED' }), []),
  }
}
