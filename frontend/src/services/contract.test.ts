/**
 * Contract tests: real backend responses against the frontend wire types (spec 23 §3.12.6 and Q1,
 * §12 and Q7/Q8; AC-23.5, AC-23.42, AC-23.43, AC-23.59, AC-23.68, AC-23.80, AC-23.83).
 * Why: the types in `types/process-discovery.ts` mirror the backend's wire models by hand, so only
 * a check against what the server really sends proves they match. The samples in
 * `src/test/fixtures/api/` are written by `backend/scripts/export_api_samples.py` (rerun:
 * `cd backend && uv run python scripts/export_api_samples.py`).
 * What: each sample goes through the HTTP client (stubbed `fetch`) and must pass the runtime guard
 * of its type; the reducer and the error table must handle them; the fake API must return the same
 * shapes. Part 2 adds the document samples (upload, list, confirm, reject, remove, a 415) and the
 * report samples (the finished EU report and the 409 `report_not_ready`). Must not: start a
 * server or call a model.
 */
import { createHttpApi, ApiError } from './api'
import { createFakeApi } from './fakeApi'
import {
  checkApiErrorBody,
  checkDiscoveryReport,
  checkDocumentList,
  checkDocumentUploadOut,
  loadReport,
  checkIdeaList,
  checkPublicConfig,
  checkSessionList,
  checkSessionOut,
  checkTaxonomy,
  checkTurnOut,
} from './wireGuards'
import { discoveryReducer, initialDiscoveryState } from '../hooks/discoveryReducer'
import { errorEffect, errorText, ERROR_TEXT } from '../utils/discoveryErrors'
import type { FieldView, SessionOut, TurnOut } from '../types/process-discovery'
import createSession from '../test/fixtures/api/create-session.json'
import turn from '../test/fixtures/api/turn.json'
import setCluster from '../test/fixtures/api/set-cluster.json'
import confirmRoles from '../test/fixtures/api/confirm-roles.json'
import finishBlocked from '../test/fixtures/api/finish-blocked.json'
import finishOk from '../test/fixtures/api/finish-ok.json'
import listSessions from '../test/fixtures/api/list-sessions.json'
import listIdeas from '../test/fixtures/api/list-ideas.json'
import taxonomy from '../test/fixtures/api/taxonomy.json'
import config from '../test/fixtures/api/config.json'
import errorKey from '../test/fixtures/api/error-visitor-key.json'
import errorNotFound from '../test/fixtures/api/error-not-found.json'
import errorInvalid from '../test/fixtures/api/error-invalid-value.json'
import uploadDocument from '../test/fixtures/api/upload-document.json'
import listDocuments from '../test/fixtures/api/list-documents.json'
import confirmProposals from '../test/fixtures/api/confirm-proposals.json'
import rejectProposals from '../test/fixtures/api/reject-proposals.json'
import removeDocument from '../test/fixtures/api/remove-document.json'
import errorDocumentType from '../test/fixtures/api/error-document-type.json'
import errorReportNotReady from '../test/fixtures/api/error-report-not-ready.json'
import report from '../test/fixtures/api/report.json'
import { PART_KEYS } from '../types/report'
import type { DocumentUploadOut } from '../types/process-discovery'

function serve(status: number, body: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({ ok: status >= 200 && status < 300, status, text: async () => JSON.stringify(body) }),
  )
}

afterEach(() => vi.unstubAllGlobals())

const api = createHttpApi(() => 'Visitorkeyvisitorkey12')

describe('real samples parse into the wire types (AC-23.5)', () => {
  it.each<[string, unknown, () => Promise<unknown>, (x: unknown) => string[]]>([
    ['create session', createSession, () => api.createSession({ displayName: 'Anna' }), checkSessionOut],
    ['turn', turn, () => api.sendMessage('s', 'hi'), checkTurnOut],
    ['set cluster', setCluster, () => api.setCluster('s', 'FIN'), checkSessionOut],
    ['confirm roles', confirmRoles, () => api.confirm('s', 'roles'), checkSessionOut],
    ['finish ok', finishOk, () => api.finish('s'), checkSessionOut],
    ['list sessions', listSessions, () => api.listSessions(), checkSessionList],
    ['list ideas', listIdeas, () => api.listIdeas(), checkIdeaList],
    ['taxonomy', taxonomy, () => api.getTaxonomy(), checkTaxonomy],
  ])('%s', async (_name, sample, call, check) => {
    serve(200, sample)
    const result = await call()
    expect(check(result)).toEqual([])
  })

  it('real sessions carry score.progress in [0, 1] (AC-23.147)', () => {
    for (const sample of [createSession, setCluster, confirmRoles, finishOk] as unknown as SessionOut[]) {
      expect(typeof sample.score.progress).toBe('number')
      expect(sample.score.progress).toBeGreaterThanOrEqual(0)
      expect(sample.score.progress).toBeLessThanOrEqual(1)
    }
  })

  it('config matches its type (not used by part 1, kept in the contract)', () => {
    expect(checkPublicConfig(config)).toEqual([])
  })

  it('the guards reject a wrong shape, so a green test means something', () => {
    expect(checkSessionOut({ ...createSession, phase: 'nowhere' })).not.toEqual([])
    expect(checkTurnOut({ ...turn, ideasAdded: '1' })).not.toEqual([])
    expect(checkSessionOut({ ...createSession, finish: { ready: true } })).not.toEqual([])
  })

  it('a session still stored in confirm is a valid wire value (AC-23.148)', () => {
    expect(checkSessionOut({ ...createSession, phase: 'confirm' })).toEqual([])
  })

  it('every error sample is an ApiErrorBody and the client keeps code, message and reason', async () => {
    for (const body of [finishBlocked, errorKey, errorNotFound, errorInvalid]) expect(checkApiErrorBody(body)).toEqual([])
    serve(409, finishBlocked)
    await expect(api.finish('s')).rejects.toMatchObject({
      status: 409,
      code: 'map_incomplete',
      reason: 'below_gate',
    })
  })
})

describe('the reducer handles real responses (AC-23.43)', () => {
  const booted = discoveryReducer(initialDiscoveryState, { type: 'BOOT_STARTED', sessionId: createSession.id })

  it('SESSION_RECEIVED then TURN_RECEIVED replace the server slice', () => {
    const s1 = discoveryReducer(booted, {
      type: 'SESSION_RECEIVED',
      forId: createSession.id,
      session: createSession as SessionOut,
    })
    expect(s1.session?.phase).toBe('context')
    expect(s1.loading).toBe(false)
    const s2 = discoveryReducer(s1, { type: 'TURN_RECEIVED', forId: createSession.id, turn: turn as TurnOut })
    expect(s2.session?.messages.at(-1)).toEqual(turn.reply)
    expect(s2.ideasAdded).toBe(1)
  })

  it('FINISH_BLOCKED from the real 409 body sets the reason and no banner', () => {
    const s1 = discoveryReducer(booted, {
      type: 'SESSION_RECEIVED',
      forId: createSession.id,
      session: setCluster as SessionOut,
    })
    const error = new ApiError(409, finishBlocked.code, finishBlocked.message, finishBlocked.reason)
    const effect = errorEffect(error, 'finish')
    expect(effect).toEqual({ kind: 'finish_blocked', reason: 'below_gate' })
    const s2 = discoveryReducer(s1, { type: 'FINISH_BLOCKED', forId: createSession.id, reason: 'below_gate' })
    expect(s2.session?.finish).toMatchObject({ ready: false, blockedBy: 'below_gate' })
    expect(s2.error).toBeNull()
  })
})

describe('real error bodies map to the error table (AC-23.42)', () => {
  it.each<[string, number, { code: string; message: string }, string]>([
    ['visitor_key_required', 401, errorKey, ERROR_TEXT.key],
    ['not_found', 404, errorNotFound, ERROR_TEXT.notFound],
    ['invalid_value', 422, errorInvalid, ERROR_TEXT.invalid],
  ])('%s', (_code, status, body, text) => {
    expect(errorText(new ApiError(status, body.code, body.message))).toBe(text)
  })

  it('idea_started (409) is a banner with the server sentence, not a conflict reload', () => {
    const error = new ApiError(409, 'idea_started', 'A session was already started from this idea.')
    expect(errorEffect(error, 'action')).toEqual({ kind: 'banner', message: 'A session was already started from this idea.' })
  })
})

describe('the fake API returns the same shapes (spec 23 §3.12.4)', () => {
  it('session, turn, lists and taxonomy pass the same guards', async () => {
    const fake = createFakeApi({ delayMs: 0, persist: false })
    const session = await fake.createSession({ displayName: 'Anna' })
    expect(checkSessionOut(session)).toEqual([])
    let last: unknown = null
    for (let i = 0; i < 4; i++) last = await fake.sendMessage(session.id, `answer ${i}`)
    expect(checkTurnOut(last)).toEqual([])
    expect(checkSessionList(await fake.listSessions())).toEqual([])
    expect(checkIdeaList(await fake.listIdeas())).toEqual([])
    expect(checkTaxonomy(await fake.getTaxonomy())).toEqual([])
  })

  it('a complete fake map uses the real field view keys, ids and phases', async () => {
    const fake = createFakeApi({ delayMs: 0, persist: false })
    const session = await fake.createSession({})
    const turnOut = await fake.sendMessage(session.id, '/finish-ready')
    const fakeKeys = turnOut.session.fieldViews.filter((v) => !v.key.includes('substeps[')).map((v) => [v.key, v.id, v.phase])
    const realKeys = confirmRoles.fieldViews.filter((v) => !v.key.includes('substeps[')).map((v) => [v.key, v.id, v.phase])
    expect(fakeKeys).toEqual(realKeys)
    // Real step 1 is a mix step, so it carries S14 (spec 12 §3.13); compare it with the fake's first
    // judgement or mix step, and check that a fake rules step has no S14 (AC-23.151).
    const leaves = (views: Array<Pick<FieldView, 'key' | 'id'>>, k: number) =>
      views.filter((v) => v.key.startsWith(`process.substeps[${k}].`)).map((v) => [v.key.split('.').pop(), v.id])
    const kinds = turnOut.session.profile.process.substeps.map((st) => st.decision_type.kind)
    const judgementStep = kinds.findIndex((k) => k === 'judgement' || k === 'mix') + 1
    expect(confirmRoles.profile.process.substeps[0].decision_type.kind).toBe('mix')
    expect(leaves(turnOut.session.fieldViews, judgementStep)).toEqual(leaves(confirmRoles.fieldViews, 1))
    const rulesStep = kinds.indexOf('rules') + 1
    expect(rulesStep).toBeGreaterThan(0)
    expect(leaves(turnOut.session.fieldViews, rulesStep).map(([, id]) => id)).not.toContain('S14')
  })

  it('uses the real error codes: invalid_value for a bad message, idea_started for a second start', async () => {
    const fake = createFakeApi({ delayMs: 0, persist: false })
    const session = await fake.createSession({})
    await expect(fake.sendMessage(session.id, '   ')).rejects.toMatchObject({ status: 422, code: 'invalid_value' })
    for (let i = 0; i < 4; i++) await fake.sendMessage(session.id, `answer ${i}`)
    const [idea] = (await fake.listIdeas()).ideas
    await fake.startIdea(idea.id)
    await expect(fake.startIdea(idea.id)).rejects.toMatchObject({ status: 409, code: 'idea_started' })
  })
})

describe('document samples (AC-23.59)', () => {
  it.each<[string, unknown, () => Promise<unknown>, (x: unknown) => string[]]>([
    ['confirm proposals', confirmProposals, () => api.confirmProposals('s', ['process.trigger']), checkSessionOut],
    ['reject proposals', rejectProposals, () => api.rejectProposals('s', ['process.end_result']), checkSessionOut],
    ['remove document', removeDocument, () => api.removeDocument('s', 'd'), checkSessionOut],
    ['report', report, () => api.getReport('s'), checkDiscoveryReport],
  ])('%s', async (_name, sample, call, check) => {
    serve(200, sample)
    expect(check(await call())).toEqual([])
  })

  it('upload and list samples pass their guards; the session carries the documents', () => {
    expect(checkDocumentUploadOut(uploadDocument)).toEqual([])
    expect(checkDocumentList(listDocuments)).toEqual([])
    expect(uploadDocument.session.documents[0]).toEqual(uploadDocument.document)
    expect(uploadDocument.session.fieldViews.some((v) => v.status === 'proposed' && v.source === 'document' && v.quote)).toBe(true)
  })

  it('a removed document leaves its confirmed value with documentName null', () => {
    const trigger = removeDocument.fieldViews.find((v) => v.key === 'process.trigger')
    expect(trigger).toMatchObject({ status: 'complete', source: 'document', documentName: null })
    expect(removeDocument.documents).toEqual([])
  })

  it('the reducer takes the real upload reply (AC-23.80)', () => {
    const id = uploadDocument.session.id
    let s = discoveryReducer(initialDiscoveryState, { type: 'BOOT_STARTED', sessionId: id })
    s = discoveryReducer(s, { type: 'UPLOAD_STARTED', forId: id, name: 'x.docx' })
    s = discoveryReducer(s, { type: 'DOCUMENT_UPLOADED', forId: id, upload: uploadDocument as unknown as DocumentUploadOut })
    expect(s.session?.documents).toHaveLength(1)
    expect(s.documentNotice).toBe(uploadDocument.report.message)
    expect(s.pending.uploading).toBeNull()
  })

  it('the real 415 body maps to the panel with the server sentence (AC-23.68)', () => {
    expect(checkApiErrorBody(errorDocumentType)).toEqual([])
    expect(errorEffect(new ApiError(415, errorDocumentType.code, errorDocumentType.message), 'upload')).toEqual({
      kind: 'documents',
      message: errorDocumentType.message,
    })
  })
})

describe('report sample (spec 23 Q7, Q8; AC-23.83; report v2, AC-23.152)', () => {
  it('has the cover and the six v2 parts in order, numbered 1–6, every number and level a string', () => {
    const loaded = loadReport(report)
    expect(loaded.cover).not.toBeNull()
    expect(PART_KEYS).toEqual(['summary', 'process', 'measures', 'map', 'steps', 'feasibility'])
    PART_KEYS.forEach((key, i) => expect(loaded[key]?.number).toBe(i + 1))
    expect(report.summary.sentences.length).toBeGreaterThan(0)
    expect(report.steps.rows.every((r) => typeof r.hours === 'string' && typeof r.levelLabel === 'string')).toBe(true)
    expect(report.feasibility.questions.map((q) => q.key)).toEqual(['q1', 'q2', 'q3'])
    expect(report.feasibility.readiness).toHaveLength(6)
    expect(report.feasibility.bullets.length).toBeLessThanOrEqual(5)
    for (const old of ['atAGlance', 'route', 'assessment', 'potential', 'readiness', 'path', 'gaps']) expect(report).not.toHaveProperty(old)
  })

  it('a v1 report (old parts, no summary or feasibility) fails the guard (AC-23.152)', () => {
    const v1 = { ...report, atAGlance: {} } as Record<string, unknown>
    delete v1.summary
    delete v1.feasibility
    expect(checkDiscoveryReport(v1)).toEqual(expect.arrayContaining(['$.summary: missing', '$.feasibility: missing']))
  })

  it('a question key outside q1–q3 fails the guard (AC-23.152)', () => {
    const bad = structuredClone(report)
    ;(bad.feasibility.questions[0] as { key: string }).key = 'q4'
    expect(checkDiscoveryReport(bad).some((p) => p.startsWith('$.feasibility.questions[0].key'))).toBe(true)
  })

  it('a part of the wrong shape is treated as missing, not as a page error', () => {
    const broken = { ...report, steps: { number: 5 }, map: null }
    delete (broken as Record<string, unknown>).feasibility
    const loaded = loadReport(broken)
    expect(loaded.steps).toBeNull()
    expect(loaded.map).toBeNull()
    expect(loaded.feasibility).toBeNull()
    expect(loaded.summary).not.toBeNull()
  })

  it('the 409 report_not_ready body is an ApiErrorBody', async () => {
    expect(checkApiErrorBody(errorReportNotReady)).toEqual([])
    serve(409, errorReportNotReady)
    await expect(api.getReport('s')).rejects.toMatchObject({ status: 409, code: 'report_not_ready' })
  })
})

describe('the fake returns the same document and report shapes', () => {
  it('upload, removal and the report pass the guards', async () => {
    const fake = createFakeApi({ delayMs: 0, persist: false })
    const s = await fake.createSession({})
    const up = await fake.uploadDocument(s.id, new File(['x'], 'procedure.docx'))
    expect(checkDocumentUploadOut(up)).toEqual([])
    expect(checkSessionOut(await fake.removeDocument(s.id, up.document.id))).toEqual([])
    await fake.sendMessage(s.id, '/finish-ready')
    await fake.confirm(s.id, 'substeps')
    await fake.finish(s.id)
    expect(checkDiscoveryReport(await fake.getReport(s.id))).toEqual([])
  })
})
