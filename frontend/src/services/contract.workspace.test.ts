/**
 * Contract tests of the workspace: real spec 21 samples against the frontend types (spec 23 §20,
 * §21 "Implications"; Q14 — the server's names win; AC-23.111, AC-23.139).
 * Why: `types/workspace.ts` mirrors `backend/app/models/workspace_wire.py` by hand; only the
 * recorded responses in `src/test/fixtures/api/review-*.json` prove that the list, the session
 * view (finished and active), the conversation and the workspace errors have the shape the
 * screens read, and that the fake API returns the same shapes.
 * What: each sample goes through the HTTP client (stubbed `fetch`) and its runtime guard; the
 * error samples go through the workspace error helpers. Must not: start a server.
 */
import { createHttpApi } from './api'
import { createFakeApi, FAKE_SPECIALIST_TOKEN } from './fakeApi'
import { checkApiErrorBody, checkConversationOut, checkReviewListOut, checkReviewSessionOut, loadReport } from './wireGuards'
import { isSessionEnded, workspaceErrorText } from '../utils/discoveryErrors'
import reviewList from '../test/fixtures/api/review-list.json'
import reviewSession from '../test/fixtures/api/review-session.json'
import reviewSessionActive from '../test/fixtures/api/review-session-active.json'
import reviewConversation from '../test/fixtures/api/review-conversation.json'
import errorToken from '../test/fixtures/api/error-workspace-token.json'
import errorEtag from '../test/fixtures/api/error-etag-required.json'
import { PART_KEYS } from '../types/report'

function serve(status: number, body: unknown) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: status >= 200 && status < 300, status, text: async () => JSON.stringify(body) }))
}

afterEach(() => vi.unstubAllGlobals())

const api = createHttpApi(() => 'Visitorkeyvisitorkey12', () => 'tok.en')
const NONE = { status: null, cluster: null, q: '' }

describe('real workspace samples parse into the wire types', () => {
  it.each<[string, unknown, () => Promise<unknown>, (x: unknown) => string[]]>([
    ['review list', reviewList, () => api.reviewList(NONE), checkReviewListOut],
    ['review session (finished)', reviewSession, () => api.reviewSession('s'), checkReviewSessionOut],
    ['review session (active)', reviewSessionActive, () => api.reviewSession('s'), checkReviewSessionOut],
    ['conversation', reviewConversation, () => api.reviewConversation('s'), checkConversationOut],
  ])('%s', async (_name, sample, call, check) => {
    serve(200, sample)
    expect(check(await call())).toEqual([])
  })

  it('the finished view carries a full report and display-text cells; the active one has no report', () => {
    const report = loadReport(reviewSession.report)
    for (const key of PART_KEYS) expect(report[key], key).not.toBeNull()
    expect(reviewSession.steps.rows.every((r) => r.cells.every((c) => typeof c.value === 'string'))).toBe(true)
    expect(reviewSessionActive.report).toBeNull()
    expect(reviewSessionActive.rawSteps).toBeNull()
    expect(reviewSession.summary.completeness).toBeLessThanOrEqual(1)
  })
})

describe('workspace error samples', () => {
  it('a 401 workspace_code_required ends the session', async () => {
    expect(checkApiErrorBody(errorToken)).toEqual([])
    serve(401, errorToken)
    const error = await api.reviewList(NONE).catch((e: unknown) => e)
    expect(isSessionEnded(error)).toBe(true)
  })

  it('a 428 etag_required gets the fallback sentence', async () => {
    expect(checkApiErrorBody(errorEtag)).toEqual([])
    serve(428, errorEtag)
    const error = await api.deleteReviewSession('s', '"e"').catch((e: unknown) => e)
    expect(workspaceErrorText(error)).toBe('Something went wrong. Please try again.')
  })
})

describe('the fake returns the same shapes', () => {
  const fake = createFakeApi({ delayMs: 0, persist: false, workspaceSeed: true, getToken: () => FAKE_SPECIALIST_TOKEN })

  it('list, views of every seed and a conversation', async () => {
    const list = await fake.reviewList(NONE)
    expect(checkReviewListOut(list)).toEqual([])
    for (const row of list.rows) {
      expect(checkReviewSessionOut(await fake.reviewSession(row.id)), row.id).toEqual([])
      expect(checkConversationOut(await fake.reviewConversation(row.id)), row.id).toEqual([])
    }
  })
})
