/**
 * Tests for the interview page reducer, one or more cases per action of spec 23 §3.10 (AC-23.43).
 * Why: every write returns the full `SessionOut`; the rule "a response replaces the server slice
 * and never touches the UI slice" and "a result for another session is ignored" protect open
 * dialogs, the picker and composer text from late replies.
 * Rules: pure reducer tests, no rendering; the hook's async flows are covered by the page tests.
 */
import { buildSession, readySession, stepsSession, summary } from '../test/fixtures/sessions'
import { discoveryReducer, initialDiscoveryState, type DiscoveryState } from './discoveryReducer'
import type { Message, TurnOut } from '../types/process-discovery'

const ready = (over: Partial<DiscoveryState> = {}): DiscoveryState => ({
  ...initialDiscoveryState,
  sessionId: 's-1',
  session: buildSession(),
  ...over,
})

const optimistic: Message = { id: 'tmp', role: 'expert', text: 'Finance', at: '2026-11-19T08:01:00Z' }

describe('discoveryReducer (AC-23.43)', () => {
  it('BOOT_STARTED sets loading and clears everything else', () => {
    const s = discoveryReducer(ready({ error: 'x', locked: true, clusterPickerOpen: true }), { type: 'BOOT_STARTED', sessionId: 's-2' })
    expect(s).toEqual({ ...initialDiscoveryState, sessionId: 's-2', loading: true })
  })

  it('SESSION_RECEIVED replaces the session, adopts the id on create and clears loading', () => {
    const booting = discoveryReducer(initialDiscoveryState, { type: 'BOOT_STARTED', sessionId: null })
    const s = discoveryReducer(booting, { type: 'SESSION_RECEIVED', forId: null, session: buildSession({ id: 'new' }) })
    expect(s.sessionId).toBe('new')
    expect(s.session?.id).toBe('new')
    expect(s.loading).toBe(false)
  })

  it('a response replaces the server slice and keeps the UI slice (dialogs, error, restore text)', () => {
    const before = ready({ clusterPickerOpen: true, sessionsModalMode: 'browse', restoreText: 'draft', error: 'banner' })
    const s = discoveryReducer(before, { type: 'SESSION_RECEIVED', forId: 's-1', session: stepsSession() })
    expect(s.session?.phase).toBe('steps')
    expect(s.clusterPickerOpen).toBe(true)
    expect(s.sessionsModalMode).toBe('browse')
    expect(s.restoreText).toBe('draft')
    expect(s.error).toBe('banner')
  })

  it('ignores a result for another session', () => {
    const before = ready({ sessionId: 's-2', session: buildSession({ id: 's-2' }) })
    const s = discoveryReducer(before, { type: 'SESSION_RECEIVED', forId: 's-1', session: stepsSession() })
    expect(s).toBe(before)
    const turn: TurnOut = { reply: optimistic, session: stepsSession(), ideasAdded: 1 }
    expect(discoveryReducer(before, { type: 'TURN_RECEIVED', forId: 's-1', turn })).toBe(before)
    expect(discoveryReducer(before, { type: 'TURN_FAILED', forId: 's-1', text: 'x', message: 'y', lock: false })).toBe(before)
    expect(discoveryReducer(before, { type: 'FINISH_BLOCKED', forId: 's-1', reason: 'below_gate' })).toBe(before)
  })

  it('MESSAGE_SENDING sets the optimistic message and sending, and resets ideasAdded', () => {
    const s = discoveryReducer(ready({ ideasAdded: 2 }), { type: 'MESSAGE_SENDING', forId: 's-1', message: optimistic })
    expect(s.optimistic).toEqual(optimistic)
    expect(s.pending.sending).toBe(true)
    expect(s.ideasAdded).toBe(0)
  })

  it('TURN_RECEIVED replaces the session, clears optimistic and sending, sets ideasAdded', () => {
    const sending = discoveryReducer(ready(), { type: 'MESSAGE_SENDING', forId: 's-1', message: optimistic })
    const turn: TurnOut = { reply: optimistic, session: stepsSession(), ideasAdded: 2 }
    const s = discoveryReducer(sending, { type: 'TURN_RECEIVED', forId: 's-1', turn })
    expect(s.optimistic).toBeNull()
    expect(s.pending.sending).toBe(false)
    expect(s.ideasAdded).toBe(2)
    expect(s.session?.phase).toBe('steps')
  })

  it('TURN_FAILED removes the optimistic message and restores the text; banner or lock', () => {
    const sending = discoveryReducer(ready(), { type: 'MESSAGE_SENDING', forId: 's-1', message: optimistic })
    const banner = discoveryReducer(sending, { type: 'TURN_FAILED', forId: 's-1', text: 'Finance', message: 'Nope.', lock: false })
    expect(banner).toMatchObject({ optimistic: null, restoreText: 'Finance', error: 'Nope.', locked: false })
    expect(banner.pending.sending).toBe(false)
    const lock = discoveryReducer(sending, { type: 'TURN_FAILED', forId: 's-1', text: 'Finance', message: null, lock: true })
    expect(lock).toMatchObject({ locked: true, error: null, restoreText: 'Finance' })
  })

  it('ACTION_STARTED / SESSION_RECEIVED set and clear the matching flag; cluster success closes the picker', () => {
    let s = discoveryReducer(ready({ clusterPickerOpen: true }), { type: 'ACTION_STARTED', forId: 's-1', kind: 'settingCluster' })
    expect(s.pending.settingCluster).toBe(true)
    s = discoveryReducer(s, { type: 'SESSION_RECEIVED', forId: 's-1', session: buildSession(), kind: 'settingCluster' })
    expect(s.pending.settingCluster).toBe(false)
    expect(s.clusterPickerOpen).toBe(false)
    s = discoveryReducer(s, { type: 'ACTION_STARTED', forId: 's-1', kind: 'confirming', target: 'roles' })
    expect(s.pending.confirming).toBe('roles')
  })

  it('ACTION_FAILED clears the flag and sets the banner, or the picker error', () => {
    let s = discoveryReducer(ready(), { type: 'ACTION_STARTED', forId: 's-1', kind: 'closing' })
    s = discoveryReducer(s, { type: 'ACTION_FAILED', forId: 's-1', kind: 'closing', message: 'Failed.', where: 'banner' })
    expect(s.pending.closing).toBe(false)
    expect(s.error).toBe('Failed.')
    let p = discoveryReducer(ready({ clusterPickerOpen: true }), { type: 'ACTION_STARTED', forId: 's-1', kind: 'settingCluster' })
    p = discoveryReducer(p, { type: 'ACTION_FAILED', forId: 's-1', kind: 'settingCluster', message: 'Gone.', where: 'picker' })
    expect(p).toMatchObject({ clusterError: 'Gone.', error: null, clusterPickerOpen: true })
  })

  it('FINISH_BLOCKED updates the reason without a banner', () => {
    const s0 = discoveryReducer(ready({ session: readySession() }), { type: 'ACTION_STARTED', forId: 's-1', kind: 'finishing' })
    const s = discoveryReducer(s0, { type: 'FINISH_BLOCKED', forId: 's-1', reason: 'roles_not_confirmed' })
    expect(s.session?.finish).toEqual({ ready: false, blockedBy: 'roles_not_confirmed', looksLikeTask: false })
    expect(s.pending.finishing).toBe(false)
    expect(s.error).toBeNull()
  })

  it('SESSION_LOCKED locks and clears every pending flag', () => {
    let s = discoveryReducer(ready(), { type: 'ACTION_STARTED', forId: 's-1', kind: 'confirming', target: 'tools' })
    s = discoveryReducer(s, { type: 'SESSION_LOCKED', forId: 's-1' })
    expect(s.locked).toBe(true)
    expect(s.pending).toEqual(initialDiscoveryState.pending)
  })

  it('picker, sessions modal, error and init-failed actions', () => {
    let s = discoveryReducer(ready(), { type: 'CLUSTER_PICKER_OPENED' })
    expect(s.clusterPickerOpen).toBe(true)
    s = discoveryReducer({ ...s, clusterError: 'x' }, { type: 'CLUSTER_PICKER_CLOSED' })
    expect(s).toMatchObject({ clusterPickerOpen: false, clusterError: null })
    s = discoveryReducer(s, { type: 'SESSIONS_SHOWN', list: [summary()], mode: 'welcome' })
    expect(s).toMatchObject({ sessionsModalMode: 'welcome', loading: false })
    expect(s.pastSessions).toHaveLength(1)
    s = discoveryReducer(s, { type: 'SESSIONS_HIDDEN' })
    expect(s.sessionsModalMode).toBeNull()
    s = discoveryReducer(s, { type: 'ERROR', message: 'Oops.' })
    expect(s.error).toBe('Oops.')
    s = discoveryReducer(s, { type: 'ERROR_CLEARED' })
    expect(s.error).toBeNull()
    s = discoveryReducer({ ...s, loading: true }, { type: 'INIT_FAILED', message: 'Not found.' })
    expect(s).toMatchObject({ initFailed: true, loading: false, error: 'Not found.' })
    s = discoveryReducer({ ...s, restoreText: 'x' }, { type: 'RESTORE_CONSUMED' })
    expect(s.restoreText).toBeNull()
  })
})
