/**
 * Tests for the in-memory fake of spec 15's interview routes (spec 23 §3.12.4–5; AC-23.47).
 * Why: the screens are built and demoed against this fake before the backend is ready, so it must
 * play the scripted monthly cost review from the welcome to a ready *Finish*, keep the server's
 * rules (closed sessions, finish gate, unknown cluster) and honour the `/error <code>` trigger.
 * Rules: no delay and no sessionStorage in tests; the same `DiscoveryApi` types as the real client.
 */
import { createFakeApi, FAKE_SCRIPT_LENGTH } from './fakeApi'
import { ApiError } from './api'
import type { SessionOut } from '../types/process-discovery'

const make = () => createFakeApi({ delayMs: 0, persist: false })

async function playToEnd(api: ReturnType<typeof make>, session: SessionOut): Promise<SessionOut> {
  let current = session
  for (let i = 0; i < FAKE_SCRIPT_LENGTH; i += 1) {
    current = (await api.sendMessage(current.id, 'yes')).session
  }
  return current
}

describe('fake API (AC-23.47)', () => {
  it('creates a session with the welcome, phase context, score 0 and Finish blocked', async () => {
    const api = make()
    const s = await api.createSession({ displayName: 'Anna' })
    expect(s).toMatchObject({ status: 'active', phase: 'context', score: { value: 0 }, finish: { ready: false, blockedBy: 'below_gate' } })
    expect(s.messages).toHaveLength(1)
    expect(s.messages[0].text).toContain('Anna')
    expect(s.fieldViews.filter((v) => v.id.startsWith('P'))).toHaveLength(16)
  })

  it('plays the cost review script to a ready Finish and keeps two ideas', async () => {
    const api = make()
    const s0 = await api.createSession({})
    const phases = new Set<string>()
    let current = s0
    let ideas = 0
    for (let i = 0; i < FAKE_SCRIPT_LENGTH; i += 1) {
      const turn = await api.sendMessage(current.id, 'yes')
      current = turn.session
      ideas += turn.ideasAdded
      phases.add(current.phase)
      expect(turn.reply).toEqual(current.messages[current.messages.length - 1])
    }
    expect([...phases]).toEqual(expect.arrayContaining(['context', 'find', 'boundaries', 'measure', 'steps', 'confirm', 'review']))
    expect(ideas).toBe(2)
    expect((await api.listIdeas()).ideas).toHaveLength(2)
    expect(current.profile.process.name).toBe('Monthly cost review')
    expect(current.profile.process.cluster.code).toBe('FIN')
    expect(current.finish).toEqual({ ready: true, blockedBy: null, looksLikeTask: false })
    const finished = await api.finish(current.id)
    expect(finished).toMatchObject({ status: 'finished', phase: 'finished', reportStatus: 'mapped' })
    const list = await api.listSessions()
    expect(list.sessions[0]).toMatchObject({ status: 'finished', processName: 'Monthly cost review' })
  })

  it('proposes the cluster FIN while asking about it', async () => {
    const api = make()
    let s = await api.createSession({})
    for (let i = 0; i < 4; i += 1) s = (await api.sendMessage(s.id, 'x')).session
    expect(s.clusterProposal).toMatchObject({ code: 'FIN', name: 'Finance' })
  })

  it('/error <code> makes the next call fail with that code', async () => {
    const api = make()
    const s = await api.createSession({})
    const armed = await api.sendMessage(s.id, '/error budget_exhausted')
    expect(armed.reply.text).toContain('budget_exhausted')
    const e = await api.getSession(s.id).catch((x: unknown) => x)
    expect(e).toBeInstanceOf(ApiError)
    expect(e).toMatchObject({ status: 429, code: 'budget_exhausted' })
    await expect(api.getSession(s.id)).resolves.toMatchObject({ id: s.id })
  })

  it('/finish-ready jumps to a complete map', async () => {
    const api = make()
    const s = await api.createSession({})
    const t = await api.sendMessage(s.id, '/finish-ready')
    expect(t.session.finish.ready).toBe(true)
  })

  it('keeps the server rules: finish gate, closed session, unknown cluster', async () => {
    const api = make()
    const s = await api.createSession({})
    await expect(api.finish(s.id)).rejects.toMatchObject({ status: 409, code: 'map_incomplete', reason: 'below_gate' })
    await expect(api.setCluster(s.id, 'XYZ')).rejects.toMatchObject({ status: 422, code: 'unknown_cluster' })
    const fin = await api.setCluster(s.id, 'IT')
    expect(fin.profile.process.cluster).toMatchObject({ code: 'IT', decided_by: 'picker' })
    const closed = await api.close(s.id)
    expect(closed).toMatchObject({ status: 'no_candidate', phase: 'no_candidate' })
    await expect(api.sendMessage(s.id, 'hi')).rejects.toMatchObject({ status: 400, code: 'session_closed' })
    await expect(api.getSession('nope')).rejects.toMatchObject({ status: 404, code: 'not_found' })
  })

  it('confirm substeps trims the declared count and closes the walk', async () => {
    const api = make()
    let s = await api.createSession({})
    for (let i = 0; i < 17; i += 1) s = (await api.sendMessage(s.id, 'x')).session
    expect(s.phase).toBe('steps')
    const rows = s.profile.process.substeps.length
    const after = await api.confirm(s.id, 'substeps')
    expect(after.profile.process.substep_count).toBe(rows)
    expect(after.profile.process.substeps_complete).toBe(true)
    expect(after.phase).toBe('confirm')
  })

  it('starts an idea once, with its name proposed for P04', async () => {
    const api = make()
    const s = await api.createSession({})
    await playToEnd(api, s)
    const idea = (await api.listIdeas()).ideas[0]
    const started = await api.startIdea(idea.id)
    const p04 = started.fieldViews.find((v) => v.id === 'P04')
    expect(p04).toMatchObject({ status: 'proposed', source: 'expert', quote: idea.words })
    await expect(api.startIdea(idea.id)).rejects.toMatchObject({ status: 409 })
    expect((await api.listIdeas()).ideas.find((i) => i.id === idea.id)?.status).toBe('started')
  })

  it('deletes everything and reports the counts', async () => {
    const api = make()
    const s = await api.createSession({})
    await playToEnd(api, s)
    await expect(api.deleteMyData()).resolves.toEqual({ sessions: 1, ideas: 2 })
    expect((await api.listSessions()).sessions).toHaveLength(0)
  })

  it('returns the nine clusters in order', async () => {
    const t = await make().getTaxonomy()
    expect(t.clusters.map((c) => c.code)).toEqual(['FIN', 'HR', 'LEG', 'IT', 'PRO', 'COM', 'KNW', 'ANL', 'GWT'])
  })
})
