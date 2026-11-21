/**
 * Tests for the in-memory fake of spec 15's interview routes (spec 23 §3.12.4–5, §11.15; AC-23.47,
 * AC-23.81, AC-23.101).
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
    expect([...phases]).toEqual(expect.arrayContaining(['context', 'find', 'boundaries', 'measure', 'steps', 'review']))
    expect(phases.has('confirm')).toBe(false)
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

  it('scores 12 points per step (S01–S11 and S13; S12 hand-over unscored) and sends S13 views (AC-23.33)', async () => {
    const api = make()
    const done = await playToEnd(api, await api.createSession({}))
    expect(done.score.totalPoints).toBe(18 + 12 * 4)
    expect(done.score.filledPoints).toBe(done.score.totalPoints)
    const s13 = done.fieldViews.find((v) => v.key === 'process.substeps[1].decision_type')
    expect(s13).toMatchObject({ id: 'S13', label: 'Rules or judgement', status: 'complete' })
    const step4 = done.fieldViews.filter((v) => v.key.startsWith('process.substeps[4].'))
    expect(step4.find((v) => v.id === 'S12')?.status).toBe('empty')
    // S14 (unscored) only for a judgement or mix step: step 4 is mix, step 1 rules (AC-23.151)
    expect(step4.map((v) => v.id).slice(-3)).toEqual(['S12', 'S13', 'S14'])
    const step1 = done.fieldViews.filter((v) => v.key.startsWith('process.substeps[1].'))
    expect(step1.map((v) => v.id).slice(-2)).toEqual(['S12', 'S13'])
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
    // Amended 2026-11-21 (spec 23 §3.6 rule 8, spec 14 §3.20 O10): the walk closes straight into review.
    expect(after.phase).toBe('review')
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

const doc = (name: string, size = 100) => new File([new Uint8Array(size)], name)
const view = (s: SessionOut, key: string) => s.fieldViews.find((v) => v.key === key)!

describe('fake documents (AC-23.81)', () => {
  it('a procedure on an empty session proposes trigger, end result and 5 step names with quotes', async () => {
    const api = make()
    const s0 = await api.createSession({})
    const progress: number[] = []
    const up = await api.uploadDocument(s0.id, doc('Cost review procedure.docx'), (p) => progress.push(p))
    expect(progress).toEqual([25, 50, 75, 100])
    expect(up.report.message).toBe(
      'I read "Cost review procedure.docx" and found 2 values and 5 steps for your process. Nothing counts until you confirm it.',
    )
    expect(view(up.session, 'process.trigger')).toMatchObject({
      status: 'proposed',
      source: 'document',
      documentName: 'Cost review procedure.docx',
      quote: 'The review starts once month-end close is completed.',
    })
    expect(view(up.session, 'process.end_result').status).toBe('proposed')
    const names = up.session.fieldViews.filter((v) => /substeps\[\d\]\.name$/.test(v.key))
    expect(names).toHaveLength(5)
    expect(names.every((v) => v.status === 'proposed' && v.quote)).toBe(true)
    expect(up.session.documents).toEqual([expect.objectContaining({ name: 'Cost review procedure.docx', kind: 'docx', proposals: 7, pending: 7 })])
    expect(up.document.pending).toBe(7)
  })

  it('never overwrites a value the expert gave (fill-only)', async () => {
    const api = make()
    let s = await api.createSession({})
    for (let i = 0; i < FAKE_SCRIPT_LENGTH; i += 1) s = (await api.sendMessage(s.id, 'yes')).session
    const before = s.profile.process.trigger
    const up = await api.uploadDocument(s.id, doc('procedure.pdf'))
    expect(up.session.profile.process.trigger).toBe(before)
    expect(up.report.message).toContain('nothing new')
  })

  it.each([
    ['map.bpmn', (s: SessionOut) => expect(view(s, 'process.substeps[1].roles').status).toBe('proposed')],
    ['empty notes.txt', (s: SessionOut) => expect(s.documents[0]).toMatchObject({ proposals: 0, outcome: 'read' })],
    ['long procedure.md', (s: SessionOut) => expect(s.documents[0].truncated).toBe(true)],
    ['failed.pdf', (s: SessionOut) => expect(s.documents[0]).toMatchObject({ outcome: 'failed', proposals: 0 })],
  ])('%s gives its scripted outcome', async (name, check) => {
    const api = make()
    const s0 = await api.createSession({})
    const up = await api.uploadDocument(s0.id, doc(name))
    check(up.session)
    if (name.startsWith('long')) expect(up.report.message).toContain('It is long, so I read only the first part.')
    if (name.startsWith('failed')) expect(up.report.message).toContain("I couldn't read this document just now.")
    if (name.startsWith('empty')) expect(up.report.message).toBe('I read "empty notes.txt" but found nothing new for the form.')
  })

  it.each([
    ['scan.pdf', 100, 422, 'document_unreadable'],
    ['inject.txt', 100, 400, 'unsafe_input'],
    ['photo.png', 100, 415, 'document_type'],
    ['big.pdf', 10 * 1_048_576 + 1, 413, 'document_too_large'],
    ['zero.pdf', 0, 422, 'document_unreadable'],
  ])('%s is refused with %i %s', async (name, size, status, code) => {
    const api = make()
    const s0 = await api.createSession({})
    await expect(api.uploadDocument(s0.id, doc(name, size))).rejects.toMatchObject({ status, code })
    expect((await api.getSession(s0.id)).documents).toEqual([])
  })

  it('refuses a sixth document with 409 document_limit', async () => {
    const api = make()
    const s0 = await api.createSession({})
    for (let i = 0; i < 5; i += 1) await api.uploadDocument(s0.id, doc(`empty ${i}.txt`))
    await expect(api.uploadDocument(s0.id, doc('empty 6.txt'))).rejects.toMatchObject({ status: 409, code: 'document_limit' })
  })

  it('confirm, reject and remove update the views and the pending counts', async () => {
    const api = make()
    const s0 = await api.createSession({})
    const up = await api.uploadDocument(s0.id, doc('procedure.docx'))
    const id = up.document.id
    let s = await api.confirmProposals(s0.id, ['process.trigger', 'not.a.proposal'])
    expect(view(s, 'process.trigger')).toMatchObject({ status: 'complete', source: 'document', documentName: 'procedure.docx' })
    expect(s.documents[0].pending).toBe(6)
    s = await api.rejectProposals(s0.id, ['process.end_result'])
    expect(view(s, 'process.end_result').status).toBe('empty')
    expect(s.profile.process.end_result).toBe('')
    expect(s.documents[0].pending).toBe(5)
    s = await api.removeDocument(s0.id, id)
    expect(s.documents).toEqual([])
    expect(s.profile.process.substeps).toEqual([])
    expect(view(s, 'process.trigger')).toMatchObject({ status: 'complete', source: 'document', documentName: null })
    await expect(api.removeDocument(s0.id, id)).rejects.toMatchObject({ status: 404, code: 'not_found' })
  })

  it('/error <code> also fails the next document call', async () => {
    const api = make()
    const s0 = await api.createSession({})
    await api.sendMessage(s0.id, '/error budget_exhausted')
    await expect(api.uploadDocument(s0.id, doc('procedure.docx'))).rejects.toMatchObject({ status: 429, code: 'budget_exhausted' })
  })

  it('getConfig returns the document limits', async () => {
    expect((await make().getConfig()).documents).toEqual({
      allowedTypes: ['pdf', 'docx', 'xlsx', 'csv', 'txt', 'md', 'bpmn', 'xml'],
      maxFiles: 5,
      maxFileMb: 10,
      maxImageMb: 5,
    })
  })
})

describe('fake report and PDF (AC-23.101)', () => {
  async function finished(api: ReturnType<typeof make>) {
    const s0 = await api.createSession({})
    await api.sendMessage(s0.id, '/finish-ready')
    await api.confirm(s0.id, 'substeps')
    return api.finish(s0.id)
  }

  it('a finished session returns the EU report; an active one is not ready', async () => {
    const api = make()
    const s = await finished(api)
    const report = await api.getReport(s.id)
    expect(report.summary.sentences).toContain('About 342 hours a year go into this process today: a moderate process.')
    const active = await api.createSession({})
    await expect(api.getReport(active.id)).rejects.toMatchObject({ status: 409, code: 'report_not_ready' })
    await expect(api.getReport('nope')).rejects.toMatchObject({ status: 404 })
  })

  it('/report-failed steps marks the steps part; /report-missing map leaves the map out (report v2)', async () => {
    const api = make()
    const s = await finished(api)
    const extra = await api.createSession({})
    await api.sendMessage(extra.id, '/report-failed steps')
    const failed = await api.getReport(s.id)
    expect(failed.steps.note?.kind).toBe('failed')
    expect(failed.feasibility.note).toBeNull()
    await api.sendMessage(extra.id, '/report-missing map')
    const missing = await api.getReport(s.id)
    expect('map' in missing).toBe(false)
    expect((await api.getReport(s.id)).map).toBeDefined()
  })

  it('the PDF call returns a blob starting with %PDF and the file name', async () => {
    const api = make()
    const s = await finished(api)
    const { blob, filename } = await api.getReportPdf(s.id)
    expect((await blob.text()).startsWith('%PDF')).toBe(true)
    expect(filename).toBe('discovery-report-monthly-cost-review.pdf')
  })
})
