/**
 * Tests for the workspace part of the fake API (spec 23 §19.10; AC-23.139, AC-23.140; AC-23.145,
 * amended 2026-11-20 (open workspace)).
 * Why: the workspace screens are built and demoed against the fake before spec 21 runs, so the
 * fake must keep the server's rules: login codes, the token check, the list filters and counts,
 * the read-only view, the PDF gate and delete with an etag.
 * What: drives `createFakeApi({workspaceSeed: true})` with an injected token getter; checks the
 * seed, the filters, the triggers typed in Search, and that delete reaches the expert's Home.
 * Must not: start a server or touch the real HTTP client.
 */
import { createFakeApi, FAKE_ENGINEER_TOKEN, FAKE_SPECIALIST_TOKEN } from './fakeApi'
import { checkPublicConfig, checkReviewListOut, checkReviewSessionOut } from './wireGuards'
import type { ReviewFilters } from '../types/workspace'

const NONE: ReviewFilters = { status: null, cluster: null, q: '' }

function make(token: string | null = FAKE_SPECIALIST_TOKEN) {
  let current = token
  const api = createFakeApi({ delayMs: 0, persist: false, workspaceSeed: true, getToken: () => current })
  return { api, setToken: (t: string | null) => (current = t) }
}

describe('login (AC-23.139)', () => {
  it('demo-specialist and demo-engineer log in with their role; another code is 401', async () => {
    const { api } = make()
    const spec = await api.workspaceLogin('demo-specialist', 'Maria')
    expect(spec).toMatchObject({ token: FAKE_SPECIALIST_TOKEN, role: 'specialist', name: 'Maria' })
    expect(new Date(spec.expiresAt).getTime()).toBeGreaterThan(Date.now() + 7 * 3_600_000)
    expect(await api.workspaceLogin('demo-engineer', 'Ed')).toMatchObject({ role: 'engineer' })
    await expect(api.workspaceLogin('nope', 'Maria')).rejects.toMatchObject({ status: 401, code: 'workspace_code_invalid' })
    await expect(api.workspaceLogin('demo-specialist', 'x'.repeat(41))).rejects.toMatchObject({ status: 422 })
  })

  it('workspace calls check the token: none 401, engineer 403', async () => {
    const { api, setToken } = make(null)
    await expect(api.reviewList(NONE)).rejects.toMatchObject({ status: 401, code: 'workspace_code_required' })
    setToken(FAKE_ENGINEER_TOKEN)
    await expect(api.reviewList(NONE)).rejects.toMatchObject({ status: 403, code: 'forbidden' })
  })
})

describe('list (AC-23.139)', () => {
  it('seeds five sessions newest first with the counts', async () => {
    const { api } = make()
    const list = await api.reviewList(NONE)
    expect(checkReviewListOut(list)).toEqual([])
    expect(list.counts).toEqual({ total: 5, active: 2, finished: 2, noCandidate: 1 })
    expect(list.matching).toBe(5)
    expect(list.truncated).toBe(false)
    const times = list.rows.map((r) => r.updatedAt)
    expect([...times].sort().reverse()).toEqual(times)
    expect(list.rows.find((r) => r.status === 'active' && r.processName === null)?.messageCount).toBe(4)
  })

  it('filters by status, cluster and q (case-insensitive) with AND; counts stay before filters', async () => {
    const { api } = make()
    const finished = await api.reviewList({ ...NONE, status: 'finished' })
    expect(finished.rows.map((r) => r.status)).toEqual(['finished', 'finished'])
    expect(finished.counts.total).toBe(5)
    expect(finished.matching).toBe(2)
    expect((await api.reviewList({ ...NONE, cluster: 'PRO' })).rows.map((r) => r.processName)).toEqual(['Supplier invoice check'])
    expect((await api.reviewList({ ...NONE, q: 'COST' })).rows.map((r) => r.processName)).toEqual(['Monthly cost review'])
    expect((await api.reviewList({ ...NONE, q: 'legal' })).rows).toHaveLength(1)
    expect((await api.reviewList({ ...NONE, q: 'seed-ended' })).rows).toHaveLength(1)
    expect((await api.reviewList({ status: 'active', cluster: 'FIN', q: '' })).rows).toHaveLength(0)
    await expect(api.reviewList({ ...NONE, q: 'x'.repeat(101) })).rejects.toMatchObject({ status: 422, code: 'invalid_value' })
  })
})

describe('session view, PDF, delete (AC-23.139)', () => {
  it('the finished seed has a report, display-text cells and a different first version', async () => {
    const { api } = make()
    const view = await api.reviewSession('seed-cost-review')
    expect(checkReviewSessionOut(view)).toEqual([])
    expect(view.report).not.toBeNull()
    expect(view.rawSteps).not.toBeNull()
    expect(view.steps.stepNames[1]).toBe('Consolidate')
    expect(view.rawSteps!.stepNames[1]).toBe('Merge the files')
    expect(view.steps.rows.every((r) => r.cells.every((c) => typeof c.value === 'string'))).toBe(true)
    expect(view.documents.map((d) => d.outcome)).toEqual(['read', 'failed'])
    expect(view.summary.status).toBe('finished')
  })

  it('an active seed has no report and no first version', async () => {
    const { api } = make()
    const view = await api.reviewSession('seed-onboarding')
    expect(view.report).toBeNull()
    expect(view.rawSteps).toBeNull()
    expect(view.summary.phase).toBe('steps')
  })

  it('the PDF before finish is 409 report_not_ready; after finish a PDF blob', async () => {
    const { api } = make()
    await expect(api.getReviewReportPdf('seed-onboarding')).rejects.toMatchObject({ status: 409, code: 'report_not_ready' })
    const pdf = await api.getReviewReportPdf('seed-cost-review')
    expect(pdf.blob.type).toBe('application/pdf')
  })

  it('the conversation returns the stored messages in order', async () => {
    const { api } = make()
    const conv = await api.reviewConversation('seed-cost-review')
    expect(conv.sessionId).toBe('seed-cost-review')
    expect(conv.messages.length).toBeGreaterThanOrEqual(25)
    expect(conv.messages[0].role).toBe('agent')
  })

  it('delete with a stale etag is 409; with the right one the session leaves the workspace and Home', async () => {
    const { api } = make()
    const mine = await api.createSession({})
    await api.sendMessage(mine.id, 'Finance control')
    const view = await api.reviewSession(mine.id)
    await expect(api.deleteReviewSession(mine.id, '"e0"')).rejects.toMatchObject({ status: 409, code: 'conflict' })
    await api.deleteReviewSession(mine.id, view.etag)
    await expect(api.reviewSession(mine.id)).rejects.toMatchObject({ status: 404 })
    expect((await api.listSessions()).sessions.map((s) => s.id)).not.toContain(mine.id)
    expect((await api.reviewList(NONE)).counts.total).toBe(5)
  })

  it('seeded sessions are not listed on the expert Home', async () => {
    const { api } = make()
    expect((await api.listSessions()).sessions).toEqual([])
  })
})

describe('triggers typed in Search (AC-23.140)', () => {
  it('/error <code> fails the next workspace call and is not used as q', async () => {
    const { api } = make()
    const list = await api.reviewList({ ...NONE, q: '/error internal_error' })
    expect(list.rows).toHaveLength(5)
    await expect(api.reviewSession('seed-cost-review')).rejects.toMatchObject({ status: 500, code: 'internal_error' })
    await expect(api.reviewSession('seed-cost-review')).resolves.toBeTruthy()
  })

  it('/expire makes the next call 401 workspace_code_required', async () => {
    const { api } = make()
    await api.reviewList({ ...NONE, q: '/expire' })
    await expect(api.reviewList(NONE)).rejects.toMatchObject({ status: 401, code: 'workspace_code_required' })
  })

  it('/touch <id> changes the etag so the next delete is 409', async () => {
    const { api } = make()
    const view = await api.reviewSession('seed-ended')
    await api.reviewList({ ...NONE, q: '/touch seed-ended' })
    await expect(api.deleteReviewSession('seed-ended', view.etag)).rejects.toMatchObject({ status: 409, code: 'conflict' })
  })
})

describe('open workspace (AC-23.145, amended 2026-11-20)', () => {
  it('config says open, any valid name logs in as specialist whatever the code, delete is 403', async () => {
    const api = createFakeApi({ delayMs: 0, persist: false, workspaceSeed: true, workspaceOpen: true, getToken: () => FAKE_SPECIALIST_TOKEN })
    const config = await api.getConfig()
    expect(config.workspaceOpen).toBe(true)
    expect(checkPublicConfig(config)).toEqual([])
    for (const code of ['', 'nope', 'demo-engineer']) {
      expect(await api.workspaceLogin(code, 'Maria')).toMatchObject({ token: FAKE_SPECIALIST_TOKEN, role: 'specialist', name: 'Maria' })
    }
    await expect(api.workspaceLogin('', '')).rejects.toMatchObject({ status: 422 })
    const [row] = (await api.reviewList(NONE)).rows
    const view = await api.reviewSession(row.id)
    await expect(api.deleteReviewSession(row.id, view.etag)).rejects.toMatchObject({
      status: 403,
      code: 'forbidden',
      message: 'Deleting is switched off on this open demo.',
    })
    expect((await api.reviewList(NONE)).rows).toHaveLength(5)
  })

  it('closed by default: config says false and a guard without workspaceOpen fails', async () => {
    const { api } = make()
    const config = await api.getConfig()
    expect(config.workspaceOpen).toBe(false)
    const withoutFlag: Record<string, unknown> = { ...config }
    delete withoutFlag.workspaceOpen
    expect(checkPublicConfig(withoutFlag)).not.toEqual([])
  })
})
