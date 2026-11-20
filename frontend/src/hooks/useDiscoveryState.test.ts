/**
 * Tests for the interview page reducer, one or more cases per action of spec 23 §3.10 and §11.9
 * (AC-23.43, AC-23.66, AC-23.80).
 * Why: every write returns the full `SessionOut`; the rule "a response replaces the server slice
 * and never touches the UI slice" and "a result for another session is ignored" protect open
 * dialogs, the picker and composer text from late replies.
 * Rules: pure reducer tests, no rendering; the hook's async flows are covered by the page tests.
 */
import { buildSession, readySession, stepsSession, summary } from '../test/fixtures/sessions'
import { discoveryReducer, initialDiscoveryState, isWriting, type DiscoveryState } from './discoveryReducer'
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

describe('document actions (AC-23.80)', () => {
  const doc = { id: 'd1', name: 'p.docx', kind: 'docx', bytes: 1, chars: 1, truncated: false, uploadedAt: 'x', outcome: 'read' as const, proposals: 2, pending: 2 }
  const upload = {
    session: buildSession({ documents: [doc] }),
    document: doc,
    report: {
      documentId: 'd1',
      outcome: 'read' as const,
      reader: 'model' as const,
      truncated: false,
      offered: { fields: 2, steps: 0, cells: 0 },
      kept: { fields: 2, steps: 0, cells: 0 },
      dropped: 0,
      skipped: [],
      stepList: 0,
      message: 'I read "p.docx" and found 2 values for your process. Nothing counts until you confirm it.',
      documentRole: 'whole_process',
      targetStep: null,
      targetSource: 'none' as const,
      fromImage: false,
      conflicts: 0,
    },
    reply: { id: 'm9', role: 'agent' as const, text: 'From "p.docx" I\'d fill: …', at: 'x' },
  }

  it('UPLOAD_STARTED sets the upload and clears the notice and the error', () => {
    const s = discoveryReducer(ready({ documentNotice: 'old', documentError: 'bad' }), { type: 'UPLOAD_STARTED', forId: 's-1', name: 'p.docx' })
    expect(s.pending.uploading).toEqual({ name: 'p.docx', percent: 0, stage: 'sending' })
    expect(s.documentNotice).toBeNull()
    expect(s.documentError).toBeNull()
  })

  it('UPLOAD_PROGRESS follows the percent and switches to reading at 100', () => {
    let s = discoveryReducer(ready(), { type: 'UPLOAD_STARTED', forId: 's-1', name: 'p.docx' })
    s = discoveryReducer(s, { type: 'UPLOAD_PROGRESS', forId: 's-1', percent: 62 })
    expect(s.pending.uploading).toMatchObject({ percent: 62, stage: 'sending' })
    s = discoveryReducer(s, { type: 'UPLOAD_PROGRESS', forId: 's-1', percent: 100 })
    expect(s.pending.uploading).toMatchObject({ percent: null, stage: 'reading' })
  })

  it('DOCUMENT_UPLOADED replaces only the server slice and keeps the UI slice', () => {
    const before = discoveryReducer(ready({ restoreText: 'draft', error: 'banner' }), { type: 'UPLOAD_STARTED', forId: 's-1', name: 'p.docx' })
    const s = discoveryReducer(before, { type: 'DOCUMENT_UPLOADED', forId: 's-1', upload })
    expect(s.session?.documents).toEqual([doc])
    expect(s.documentNotice).toBe(upload.report.message)
    expect(s.pending.uploading).toBeNull()
    expect(s.restoreText).toBe('draft')
    expect(s.error).toBe('banner')
  })

  it('DOCUMENT_REJECTED shows the sentence and clears the upload', () => {
    const before = discoveryReducer(ready(), { type: 'UPLOAD_STARTED', forId: 's-1', name: 'p.docx' })
    const s = discoveryReducer(before, { type: 'DOCUMENT_REJECTED', forId: 's-1', message: 'This file is larger than 10 MB.' })
    expect(s.documentError).toBe('This file is larger than 10 MB.')
    expect(s.pending.uploading).toBeNull()
  })

  it('DOCUMENT_REMOVING and PROPOSALS_STARTED set their flags; SESSION_RECEIVED clears them', () => {
    let s = discoveryReducer(ready(), { type: 'DOCUMENT_REMOVING', forId: 's-1', docId: 'd1' })
    expect(s.pending.removingDocument).toBe('d1')
    s = discoveryReducer(s, { type: 'SESSION_RECEIVED', forId: 's-1', session: buildSession(), kind: 'removingDocument' })
    expect(s.pending.removingDocument).toBeNull()
    s = discoveryReducer(s, { type: 'PROPOSALS_STARTED', forId: 's-1', keys: ['process.trigger'], kind: 'reject' })
    expect(s.pending.proposals).toEqual({ keys: ['process.trigger'], kind: 'reject' })
    s = discoveryReducer(s, {
      type: 'SESSION_RECEIVED',
      forId: 's-1',
      session: buildSession(),
      kind: 'proposals',
      notice: 'Removed. The agent will ask you about Trigger.',
    })
    expect(s.pending.proposals).toBeNull()
    expect(s.proposalNotice).toBe('Removed. The agent will ask you about Trigger.')
    s = discoveryReducer(s, { type: 'MESSAGE_SENDING', forId: 's-1', message: optimistic })
    expect(s.proposalNotice).toBeNull()
  })

  it('ACTION_FAILED with where "documents" writes the panel error, not the banner', () => {
    const before = discoveryReducer(ready(), { type: 'UPLOAD_STARTED', forId: 's-1', name: 'p.docx' })
    const s = discoveryReducer(before, { type: 'ACTION_FAILED', forId: 's-1', kind: 'uploading', message: 'Nope.', where: 'documents' })
    expect(s.documentError).toBe('Nope.')
    expect(s.error).toBeNull()
    expect(s.pending.uploading).toBeNull()
  })

  it('ignores every document result for another session', () => {
    const before = ready({ sessionId: 's-2', session: buildSession({ id: 's-2' }) })
    expect(discoveryReducer(before, { type: 'UPLOAD_STARTED', forId: 's-1', name: 'x' })).toBe(before)
    expect(discoveryReducer(before, { type: 'UPLOAD_PROGRESS', forId: 's-1', percent: 5 })).toBe(before)
    expect(discoveryReducer(before, { type: 'DOCUMENT_UPLOADED', forId: 's-1', upload })).toBe(before)
    expect(discoveryReducer(before, { type: 'DOCUMENT_REJECTED', forId: 's-1', message: 'x' })).toBe(before)
    expect(discoveryReducer(before, { type: 'DOCUMENT_REMOVING', forId: 's-1', docId: 'd' })).toBe(before)
    expect(discoveryReducer(before, { type: 'PROPOSALS_STARTED', forId: 's-1', keys: ['k'], kind: 'confirm' })).toBe(before)
  })

  it('isWriting is true while an upload, a removal or a ✓ / ✎ runs (AC-23.66)', () => {
    expect(isWriting(initialDiscoveryState.pending)).toBe(false)
    expect(isWriting({ ...initialDiscoveryState.pending, uploading: { name: 'x', percent: 0, stage: 'sending' } })).toBe(true)
    expect(isWriting({ ...initialDiscoveryState.pending, removingDocument: 'd' })).toBe(true)
    expect(isWriting({ ...initialDiscoveryState.pending, proposals: { keys: ['k'], kind: 'confirm' } })).toBe(true)
    expect(isWriting({ ...initialDiscoveryState.pending, sending: true })).toBe(false)
  })
})
