/**
 * In-memory fake of the interview routes of spec 15 part 2 (spec 23 §3.12.4–5; AC-23.47).
 * Why: the screens are built, tested and demoed before the backend is ready. The fake implements
 * the same `DiscoveryApi` as the HTTP client, plays a scripted monthly cost review, and keeps the
 * server's rules (closed sessions, the *Finish* gate, unknown clusters, ideas started once).
 * Rules: only the fake builds field views, scores and *Finish* state; real client code never does.
 * It is loaded by dynamic import in fake mode only and a production build refuses fake mode
 * (AC-23.48). Error codes, statuses and sentences are the server's own (`api/errors.py`), checked
 * against recorded responses in `contract.test.ts`. Manual triggers: `/error <code>` fails the next call
 * (also a document, proposal, report or PDF call), `/finish-ready` completes the map,
 * `/report-failed <part>` and `/report-missing <part>` shape the next report.
 * Part 2 (spec 23 §11.15; AC-23.81, AC-23.101): document upload with progress and scripted
 * outcomes by file name, fill-only proposals with quotes, ✓ / ✎, removal, the report and the PDF.
 * Divergence kept on purpose: like the built server, a report asked for before *Finish* is 409
 * `report_not_ready` (the spec text said 404).
 * Part 3 (spec 23 §19.10; AC-23.139, AC-23.140): the workspace login (`demo-specialist`,
 * `demo-engineer`), the token check of every workspace call, five seeded sessions (option
 * `workspaceSeed`; hidden from the expert's Home), the review list with spec 21 §3.2 filters, the
 * read-only view with display-text grid cells, the conversation, the PDF and delete with an etag.
 * Workspace triggers typed in the Search box: `/error <code>`, `/expire`, `/touch <id>`.
 */
import { ApiError, type DiscoveryApi } from './api'
import {
  BPMN_LANES,
  CLUSTERS,
  COST_REVIEW_ANSWERS,
  COST_REVIEW_STEPS,
  DOCUMENT_SENTENCES,
  FAKE_CONFIG,
  FAKE_PDF,
  IDEAS,
  PROCEDURE_FIELDS,
  PROCEDURE_STEPS,
  PROCESS_FIELDS,
  SCRIPT,
  STEP_FIELDS,
  WORKSPACE_SEED,
  emptyProfile,
  emptyStep,
  type WorkspaceSeedSession,
} from './fakeData'
import { readWorkspaceToken } from '../access/workspaceToken'
import type { ReviewRow, ReviewSessionOut, StepGrid } from '../types/workspace'
import { euReport, withFailedNote } from '../test/fixtures/report'
import { formatValue, getValue } from '../utils/discoveryFormat'
import { PART_KEYS, type DiscoveryReport } from '../types/report'
import { typeSentence } from '../utils/documentLimits'
import type {
  ApiErrorCode,
  DocumentOut,
  DocumentUploadOut,
  FieldStatus,
  FieldView,
  FinishState,
  Idea,
  Message,
  Phase,
  Profile,
  SessionOut,
  SessionSummary,
  Step,
} from '../types/process-discovery'

export const FAKE_SCRIPT_LENGTH = SCRIPT.length

interface FakeSession {
  id: string
  status: SessionOut['status']
  displayName: string | null
  createdAt: string
  updatedAt: string
  finishedAt: string | null
  messages: Message[]
  profile: Profile
  /** Keys proposed but not yet confirmed, with their quote (an idea's words). */
  proposals: Record<string, string>
  turn: number
  proposingCluster: boolean
  /** Uploaded documents (counts are derived from `docProposals`). */
  documents?: Array<Omit<DocumentOut, 'pending'>>
  /** Keys proposed by a document and not yet settled: document id and quote. */
  docProposals?: Record<string, { docId: string; quote: string }>
  /** Keys confirmed from a document: the document id (the name is looked up; gone = removed). */
  docConfirmed?: Record<string, { docId: string; quote: string }>
  /** Part 3: a workspace seed (not listed on the expert's Home). */
  seeded?: boolean
  /** Part 3: the steps as the expert first told them, or null when nothing froze them. */
  rawSteps?: Step[] | null
  /** Part 3: the etag counter, bumped on every write. */
  etag?: number
}

interface Store {
  sessions: FakeSession[]
  ideas: Idea[]
  seeded?: boolean
}

export interface FakeApiOptions {
  /** Fixed delay, or a [min, max] range in ms. Default 300–800 ms to show spinners. */
  delayMs?: number | [number, number]
  /** Keep data in sessionStorage so a reload keeps it. Default true. */
  persist?: boolean
  /** Part 3: add the five workspace seed sessions (spec 23 §19.10.3). Default false. */
  workspaceSeed?: boolean
  /** Part 3: the workspace token of the caller. Default: the stored one. */
  getToken?: () => string | null
  /** Open demo workspace (spec 23 §19.10.9, amended 2026-11-20): name-only login, delete 403. Default false. */
  workspaceOpen?: boolean
}

export const FAKE_SPECIALIST_TOKEN = 'fake.specialist'
export const FAKE_ENGINEER_TOKEN = 'fake.engineer'
const FAKE_CODES: Record<string, { token: string; role: 'specialist' | 'engineer' }> = {
  'demo-specialist': { token: FAKE_SPECIALIST_TOKEN, role: 'specialist' },
  'demo-engineer': { token: FAKE_ENGINEER_TOKEN, role: 'engineer' },
}

const STORAGE_KEY = 'discovery_fake_store'
/** The server's fixed sentence for every 404 (backend `api/errors.py`). */
const NOT_FOUND = 'Not found.'

const ERROR_STATUS: Record<ApiErrorCode, number> = {
  session_closed: 400,
  unsafe_input: 400,
  not_found: 404,
  map_incomplete: 409,
  conflict: 409,
  unknown_cluster: 422,
  invalid_value: 422,
  idea_started: 409,
  rate_limited: 429,
  budget_exhausted: 429,
  model_unavailable: 503,
  store_unavailable: 503,
  internal_error: 500,
  visitor_key_required: 401,
  network: 0,
  document_limit: 409,
  document_too_large: 413,
  document_type: 415,
  document_unreadable: 422,
  report_not_ready: 409,
  workspace_code_invalid: 401,
  workspace_code_required: 401,
  forbidden: 403,
  etag_required: 428,
}

let clockTick = 0
const now = () => new Date(Date.now() + clockTick++).toISOString()

function uid(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return `id-${Math.random().toString(36).slice(2)}-${Date.now()}`
}

/* ---- grading (fake only; the real server owns this) ---- */

const present = (v: unknown): boolean => {
  if (v === null || v === undefined) return false
  if (typeof v === 'string') return v.trim().length > 0
  if (typeof v === 'number') return true
  if (Array.isArray(v)) return v.length > 0
  return false
}

function grade(key: string, value: unknown): { status: 'complete' | 'partial' | 'empty'; missing: string[] } {
  const leaf = key.split('.').pop() ?? key
  const obj = (value ?? {}) as Record<string, unknown>
  const groups: Record<string, string[][]> = {
    cluster: [['code']],
    volume: [['count', 'period'], ['raw']],
    process_owner: [['role'], ['none_identified']],
    baseline_metric: [['value', 'unit'], ['qualitative']],
    target_metric: [['value', 'unit']],
    variation: [['same']],
    data: [['inputs', 'outputs']],
    effort: [['duration', 'frequency']],
  }
  const g = groups[leaf]
  if (g && typeof value === 'object' && !Array.isArray(value) && value !== null) {
    const has = (f: string) => (typeof obj[f] === 'boolean' ? obj[f] === true : present(obj[f]))
    if (g.some((members) => members.every(has))) return { status: 'complete', missing: [] }
    const best = [...g].sort((a, b) => b.filter(has).length - a.filter(has).length)[0]
    const missing = best.filter((f) => !has(f))
    return { status: best.some(has) ? 'partial' : 'empty', missing }
  }
  return present(value) ? { status: 'complete', missing: [] } : { status: 'empty', missing: [] }
}

function makeView(
  key: string,
  id: string,
  label: string,
  phase: Phase,
  value: unknown,
  proposalQuote: string | undefined,
  s?: FakeSession,
): FieldView {
  const fromDoc = s?.docProposals?.[key] ?? (proposalQuote === undefined ? s?.docConfirmed?.[key] : undefined)
  if (fromDoc && s) {
    const proposed = Boolean(s.docProposals?.[key])
    const { status: g } = grade(key, value)
    if (g === 'complete') {
      return {
        key,
        id,
        label,
        phase,
        status: proposed ? 'proposed' : 'complete',
        reason: '',
        missing: [],
        source: 'document',
        quote: fromDoc.quote,
        documentName: s.documents?.find((d) => d.id === fromDoc.docId)?.name ?? null,
        asks: 0,
        fromImage: false,
        conflict: null,
        items: [],
      }
    }
  }
  const { status: graded, missing } = grade(key, value)
  const status: FieldStatus = proposalQuote !== undefined && graded === 'complete' ? 'proposed' : graded
  const reason =
    status === 'complete' || status === 'proposed'
      ? ''
      : missing.length > 0 && status === 'partial'
        ? `${label} still needs: ${missing.join(', ')}.`
        : `${label} has not been answered yet.`
  return {
    key,
    id,
    label,
    phase,
    status,
    reason,
    missing,
    source: status === 'complete' || status === 'proposed' ? 'expert' : null,
    quote: status === 'proposed' ? (proposalQuote ?? null) : null,
    documentName: null,
    asks: 0,
    fromImage: false,
    conflict: null,
    items: [],
  }
}

function fieldViews(s: FakeSession): FieldView[] {
  const views = PROCESS_FIELDS.map((f) =>
    makeView(f.key, f.id, f.label, f.phase, getValue(s.profile, f.key), s.proposals[f.key], s),
  )
  s.profile.process.substeps.forEach((_, i) => {
    for (const f of STEP_FIELDS) {
      const key = `process.substeps[${i + 1}].${f.leaf}`
      views.push(makeView(key, f.id, f.label, 'steps', getValue(s.profile, key), undefined, s))
    }
  })
  return views
}

function score(views: FieldView[], p: Profile): SessionOut['score'] {
  const steps = Math.min(Math.max(p.process.substep_count ?? 0, 0), 6)
  const totalPoints = 18 + 11 * steps
  let filled = 0
  for (const v of views) {
    if (v.status !== 'complete') continue
    if (v.phase === 'steps') {
      if (!v.key.endsWith('.handover')) filled += 1
    } else {
      filled += PROCESS_FIELDS.find((f) => f.key === v.key)?.weight ?? 0
    }
  }
  const filledPoints = Math.min(filled, totalPoints)
  return { value: Math.round((filledPoints / totalPoints) * 10000) / 10000, filledPoints, totalPoints }
}

function finishState(sc: SessionOut['score'], p: Profile): FinishState {
  const blockedBy =
    sc.value < 0.8
      ? 'below_gate'
      : !p.process.substeps_complete
        ? 'substeps_incomplete'
        : !p.process.roles_confirmed
          ? 'roles_not_confirmed'
          : !p.process.tools_confirmed
            ? 'tools_not_confirmed'
            : null
  return { ready: blockedBy === null, blockedBy, looksLikeTask: false }
}

function phaseOf(s: FakeSession, views: FieldView[]): Phase {
  if (s.status === 'finished') return 'finished'
  if (s.status === 'no_candidate') return 'no_candidate'
  for (const phase of ['context', 'find', 'boundaries', 'measure', 'step_count'] as Phase[]) {
    if (views.some((v) => v.phase === phase && v.status !== 'complete')) return phase
  }
  const p = s.profile.process
  if (!p.substeps_complete) return 'steps'
  if (!p.roles_confirmed || !p.tools_confirmed) return 'confirm'
  return 'review'
}

function rebuildRollups(p: Profile): void {
  const dedupe = (items: string[]) => {
    const seen = new Set<string>()
    return items.filter((i) => {
      const k = i.toLowerCase()
      if (seen.has(k)) return false
      seen.add(k)
      return true
    })
  }
  p.process.all_roles = dedupe(
    p.process.substeps.flatMap((s) => s.roles.flatMap((r) => ('role' in r ? [r.role] : []))),
  )
  p.process.all_tools = dedupe(p.process.substeps.flatMap((s) => s.systems))
}

function toOut(s: FakeSession): SessionOut {
  const views = fieldViews(s)
  const sc = score(views, s.profile)
  const cluster = CLUSTERS[0]
  return structuredClone({
    id: s.id,
    status: s.status,
    phase: phaseOf(s, views),
    displayName: s.displayName,
    createdAt: s.createdAt,
    updatedAt: s.updatedAt,
    finishedAt: s.finishedAt,
    messages: s.messages,
    profile: s.profile,
    fieldViews: views,
    score: sc,
    finish: finishState(sc, s.profile),
    scope: null,
    clusterProposal: s.proposingCluster && s.status === 'active' ? cluster : null,
    reportStatus: s.status === 'finished' ? 'mapped' : null,
    documents: documentsOut(s),
  })
}

function documentsOut(s: FakeSession): DocumentOut[] {
  return (s.documents ?? []).map((d) => ({
    ...d,
    pending: Object.values(s.docProposals ?? {}).filter((p) => p.docId === d.id).length,
  }))
}

/** Clears one field or step cell back to its empty value (the fake's ✎ and removal). */
function clearValue(p: Profile, key: string): void {
  const cell = /^process\.substeps\[(\d+)\]\.(\w+)$/.exec(key)
  if (cell) {
    const step = p.process.substeps[Number(cell[1]) - 1] as unknown as Record<string, unknown> | undefined
    if (step) step[cell[2]] = (emptyStep() as unknown as Record<string, unknown>)[cell[2]]
    return
  }
  const leaf = key.replace(/^process\./, '')
  if (key.startsWith('process.')) {
    ;(p.process as unknown as Record<string, unknown>)[leaf] = (emptyProfile().process as unknown as Record<string, unknown>)[leaf]
  } else {
    ;(p as unknown as Record<string, unknown>)[key] = ''
  }
}

/** Drops step rows left with no answer at all (spec 17 §3.13.3). */
function dropEmptyRows(p: Profile): void {
  const blank = JSON.stringify(emptyStep())
  p.process.substeps = p.process.substeps.filter((row) => JSON.stringify(row) !== blank)
}

const extOf = (name: string) => (name.includes('.') ? name.split('.').pop()!.toLowerCase() : '')

/** What the fake "reads" from a file, by its name (spec 23 §11.15.3). */
function readDocument(s: FakeSession, docId: string, name: string): { values: number; steps: number; truncated: boolean } {
  const lower = name.toLowerCase()
  if (lower.includes('empty')) return { values: 0, steps: 0, truncated: false }
  const proposals = (s.docProposals ??= {})
  const p = s.profile.process
  let values = 0
  let steps = 0
  const bpmn = extOf(lower) === 'bpmn'
  if (!bpmn) {
    for (const f of PROCEDURE_FIELDS) {
      if (p[f.key].trim()) continue // fill-only: never overwrite a value the expert gave
      p[f.key] = f.value
      proposals[`process.${f.key}`] = { docId, quote: f.quote }
      values += 1
    }
  }
  if (p.substeps.length === 0) {
    PROCEDURE_STEPS.forEach((step, i) => {
      const row = emptyStep()
      row.name = step.name
      p.substeps.push(row)
      proposals[`process.substeps[${i + 1}].name`] = { docId, quote: step.quote }
      steps += 1
    })
    if (bpmn) {
      BPMN_LANES.forEach((lane, i) => {
        p.substeps[i].roles = [{ role: lane, contribution: '' }]
        proposals[`process.substeps[${i + 1}].roles`] = { docId, quote: `Lane: ${lane}` }
      })
    }
  }
  return { values, steps, truncated: lower.includes('long') }
}

function toSummary(s: FakeSession): SessionSummary {
  const out = toOut(s)
  return {
    id: s.id,
    status: s.status,
    phase: out.phase,
    processName: s.profile.process.name || null,
    clusterCode: s.profile.process.cluster.code || null,
    score: out.score.value,
    messageCount: s.messages.length,
    createdAt: s.createdAt,
    updatedAt: s.updatedAt,
    reportStatus: out.reportStatus,
  }
}

function completeMap(s: FakeSession): void {
  for (const turn of SCRIPT) turn.apply(s.profile)
  s.profile.process.substeps = structuredClone(COST_REVIEW_STEPS)
  s.profile.process.substep_count = COST_REVIEW_STEPS.length
  s.proposals = {}
  s.proposingCluster = false
  s.turn = SCRIPT.length
}

/* ---- workspace (part 3): the fake's version of spec 21 ---- */

/** One seed of `WORKSPACE_SEED` as a stored fake session (spec 23 §19.10.3). */
function seedSession(seed: WorkspaceSeedSession, at: number): FakeSession {
  const iso = (hoursAgo: number) => new Date(at - hoursAgo * 3_600_000).toISOString()
  const s: FakeSession = {
    id: seed.id,
    status: seed.status,
    displayName: null,
    createdAt: iso(seed.createdDaysAgo * 24 + seed.updatedHoursAgo),
    updatedAt: iso(seed.updatedHoursAgo),
    finishedAt: seed.status === 'active' ? null : iso(seed.updatedHoursAgo),
    messages: [],
    profile: emptyProfile(),
    proposals: {},
    turn: 0,
    proposingCluster: false,
    seeded: true,
    rawSteps: null,
    etag: 1,
  }
  const p = s.profile
  if (seed.fill === 'complete' || seed.fill === 'steps') {
    completeMap(s)
    p.process.substeps_complete = seed.fill === 'complete'
    p.process.roles_confirmed = seed.fill === 'complete'
    p.process.tools_confirmed = seed.fill === 'complete'
    if (seed.fill === 'steps') p.process.substeps = p.process.substeps.slice(0, 2)
  }
  if (seed.department) p.department = seed.department
  if (seed.processName) p.process.name = seed.processName
  const cluster = CLUSTERS.find((c) => c.code === seed.clusterCode)
  if (cluster) p.process.cluster = { code: cluster.code, name: cluster.name, decided_by: 'picker' }
  rebuildRollups(p)
  if (seed.rawSteps) {
    const raw = structuredClone(COST_REVIEW_STEPS)
    raw[1].name = 'Merge the files'
    raw[1].systems = ['Excel', 'Email']
    s.rawSteps = raw
  }
  s.documents = (seed.documents ?? []).map((d, i) => ({
    id: `${seed.id}-doc-${i + 1}`,
    name: d.name,
    kind: d.kind,
    bytes: d.bytes,
    chars: d.outcome === 'read' ? 1000 : 0,
    truncated: false,
    uploadedAt: iso(seed.updatedHoursAgo + 24),
    outcome: d.outcome,
    proposals: 0,
  }))
  // The conversation: the welcome, then the expert's answers with the agent's lines.
  let t = at - (seed.createdDaysAgo * 24 + seed.updatedHoursAgo) * 3_600_000
  const say = (role: Message['role'], text: string) => {
    t += 60_000
    s.messages.push({ id: `${seed.id}-m${s.messages.length + 1}`, role, text, at: new Date(t).toISOString() })
  }
  say('agent', 'Hello! I will help you map one process from your work in about 15 minutes.\n\n**Which department do you work in?**')
  const pairs: Array<[string, string]> =
    seed.conversation.length > 0
      ? seed.conversation
      : COST_REVIEW_ANSWERS.map((answer, i) => [answer, SCRIPT[i].reply(p)])
  for (const [expert, agentText] of pairs) {
    say('expert', expert)
    if (agentText) say('agent', agentText)
  }
  return s
}

const stepKey = (i: number, leaf: string) => `process.substeps[${i + 1}].${leaf}`

/** The step grid of spec 21 §3.3: one row per step field, one display-text cell per step. */
function stepGrid(s: FakeSession, substeps: Step[]): StepGrid {
  const view: FakeSession = { ...s, profile: { ...s.profile, process: { ...s.profile.process, substeps } } }
  const views = fieldViews(view)
  return {
    stepNames: substeps.map((st) => st.name),
    rows: STEP_FIELDS.map((f) => ({
      key: f.leaf,
      id: f.id,
      label: f.label,
      cells: substeps.map((_, i) => {
        const v = views.find((x) => x.key === stepKey(i, f.leaf))
        return {
          value: formatValue(view.profile, stepKey(i, f.leaf)),
          source: v && v.status !== 'empty' ? v.source : null,
          status: v?.status ?? null,
        }
      }),
    })),
  }
}

const blankToNull = (v: string) => (v.trim() ? v : null)

function reviewRow(s: FakeSession): ReviewRow {
  const out = toOut(s)
  const p = s.profile
  return {
    id: s.id,
    createdAt: s.createdAt,
    updatedAt: s.updatedAt,
    processName: blankToNull(p.process.name),
    department: blankToNull(p.department),
    clusterCode: blankToNull(p.process.cluster.code),
    clusterName: blankToNull(p.process.cluster.name),
    region: blankToNull(p.region),
    status: s.status,
    phase: out.phase,
    fieldsFilled: out.fieldViews.filter((v) => v.status === 'complete').length,
    fieldsTotal: out.fieldViews.length,
    steps: p.process.substeps.length,
    messageCount: s.messages.length,
    documentCount: (s.documents ?? []).length,
    simulated: false,
  }
}

function reviewSessionOut(s: FakeSession): ReviewSessionOut {
  const row = reviewRow(s)
  const out = toOut(s)
  const p = s.profile.process
  const started = p.substeps.filter((st) => JSON.stringify(st) !== JSON.stringify(emptyStep())).length
  return structuredClone({
    id: s.id,
    etag: `"e${s.etag ?? 1}"`,
    summary: {
      department: row.department,
      function: blankToNull(s.profile.user_function),
      region: row.region,
      processName: row.processName,
      clusterName: row.clusterName,
      status: s.status,
      phase: row.phase,
      fieldsFilled: row.fieldsFilled,
      fieldsTotal: row.fieldsTotal,
      stepsStarted: started,
      stepsExpected: p.substep_count ?? p.substeps.length,
      completeness: out.score.value,
      filledPoints: out.score.filledPoints,
      totalPoints: out.score.totalPoints,
      messageCount: row.messageCount,
      documentCount: row.documentCount,
    },
    steps: stepGrid(s, p.substeps),
    rawSteps: s.rawSteps ? stepGrid(s, s.rawSteps) : null,
    documents: (s.documents ?? []).map((d) => ({ name: d.name, kind: d.kind, bytes: d.bytes, uploadedAt: d.uploadedAt, outcome: d.outcome })),
    report: s.status === 'finished' ? structuredClone(euReport) : null,
    simulated: row.simulated,
  })
}

export function createFakeApi(options: FakeApiOptions = {}): DiscoveryApi {
  const persist = options.persist ?? true
  const workspaceOpen = options.workspaceOpen ?? false
  const range = options.delayMs ?? [300, 800]
  let armedError: string | null = null
  let reportFailed: string | null = null
  let reportMissing: string | null = null
  const stepMs = range === 0 ? 0 : 150
  const readMs = range === 0 ? 0 : 800
  const sleep = (ms: number) => (ms > 0 ? new Promise((r) => setTimeout(r, ms)) : Promise.resolve())

  const load = (): Store => {
    if (persist) {
      try {
        const raw = sessionStorage.getItem(STORAGE_KEY)
        if (raw) return JSON.parse(raw) as Store
      } catch {
        /* storage blocked: start empty */
      }
    }
    return { sessions: [], ideas: [] }
  }
  const store = load()
  if (options.workspaceSeed && !store.seeded) {
    const at = Date.now()
    store.sessions.push(...WORKSPACE_SEED.map((seed) => seedSession(seed, at)))
    store.seeded = true
  }
  const getToken = options.getToken ?? (() => readWorkspaceToken()?.token ?? null)
  let armedWorkspace: { code: string } | null = null
  const save = () => {
    if (!persist) return
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(store))
    } catch {
      /* storage blocked: keep in memory */
    }
  }

  const wait = () => {
    const ms = Array.isArray(range) ? range[0] + Math.random() * (range[1] - range[0]) : range
    return ms > 0 ? new Promise((r) => setTimeout(r, ms)) : Promise.resolve()
  }

  /** Every call goes through here: delay, then the armed `/error`, then the work. */
  async function call<T>(work: () => T): Promise<T> {
    await wait()
    if (armedError) {
      const code = armedError
      armedError = null
      throw new ApiError(
        ERROR_STATUS[code as ApiErrorCode] ?? 400,
        code,
        code === 'unsafe_input' ? 'That message cannot be processed. Please rephrase it.' : `Simulated ${code}.`,
        code === 'map_incomplete' ? 'below_gate' : undefined,
      )
    }
    const result = work()
    save()
    return result
  }

  /** Every workspace call: delay, the armed trigger, the token check of spec 21 §3.1, the work. */
  async function wsCall<T>(work: () => T): Promise<T> {
    await wait()
    if (armedWorkspace) {
      const { code } = armedWorkspace
      armedWorkspace = null
      throw new ApiError(ERROR_STATUS[code as ApiErrorCode] ?? 400, code, `Simulated ${code}.`)
    }
    const token = getToken()
    if (token === FAKE_ENGINEER_TOKEN) throw new ApiError(403, 'forbidden', 'This action is not available for your role.')
    if (token !== FAKE_SPECIALIST_TOKEN) throw new ApiError(401, 'workspace_code_required', 'Enter the workspace access code.')
    const result = work()
    save()
    return result
  }

  /** A Search box trigger (spec 23 §19.10.7): arms the next workspace call; true when it was one. */
  const workspaceTrigger = (q: string): boolean => {
    const text = q.trim()
    const error = /^\/error\s+(\w+)/.exec(text)
    const touch = /^\/touch\s+(\S+)/.exec(text)
    if (error) armedWorkspace = { code: error[1] }
    else if (text === '/expire') armedWorkspace = { code: 'workspace_code_required' }
    else if (touch) {
      const target = store.sessions.find((x) => x.id === touch[1])
      if (target) target.etag = (target.etag ?? 1) + 1
    } else return false
    return true
  }

  const find = (id: string): FakeSession => {
    const s = store.sessions.find((x) => x.id === id)
    if (!s) throw new ApiError(404, 'not_found', NOT_FOUND)
    return s
  }
  const writable = (id: string): FakeSession => {
    const s = find(id)
    if (s.status !== 'active') throw new ApiError(400, 'session_closed', 'This session is closed.')
    return s
  }
  const touched = (s: FakeSession) => {
    rebuildRollups(s.profile)
    s.updatedAt = now()
    s.etag = (s.etag ?? 1) + 1
    return toOut(s)
  }
  const agent = (text: string): Message => ({ id: uid(), role: 'agent', text, at: now() })

  function create(displayName?: string, ideaId?: string): SessionOut {
    const at = now()
    const name = displayName?.trim() ? displayName.trim().slice(0, 40) : null
    const s: FakeSession = {
      id: uid(),
      status: 'active',
      displayName: name,
      createdAt: at,
      updatedAt: at,
      finishedAt: null,
      messages: [],
      profile: emptyProfile(),
      proposals: {},
      turn: 0,
      proposingCluster: false,
    }
    if (ideaId) {
      const idea = store.ideas.find((i) => i.id === ideaId)
      if (!idea) throw new ApiError(404, 'not_found', NOT_FOUND)
      if (idea.status === 'started') throw new ApiError(409, 'idea_started', 'A session was already started from this idea.')
      idea.status = 'started'
      idea.startedSessionId = s.id
      s.profile.process.name = idea.name
      s.proposals['process.name'] = idea.words
    }
    s.messages.push(
      agent(
        `Hello${name ? ` ${name}` : ''}! I will help you map one process from your work in about 15 minutes. ` +
          'Everything you tell me fills in *Your process* on the right.\n\n**Which department do you work in?**',
      ),
    )
    store.sessions.unshift(s)
    return toOut(s)
  }

  return {
    createSession: ({ displayName, fromIdeaId }) => call(() => create(displayName, fromIdeaId)),

    listSessions: () =>
      call(() => ({
        sessions: store.sessions
          .filter((s) => !s.seeded)
          .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
          .map(toSummary),
      })),

    getSession: (id) => call(() => toOut(find(id))),

    deleteSession: (id) =>
      call(() => {
        find(id)
        store.sessions = store.sessions.filter((s) => s.id !== id)
      }),

    sendMessage: (id, text) =>
      call(() => {
        const s = writable(id)
        if (!text.trim() || text.length > 16000) {
          throw new ApiError(422, 'invalid_value', 'text: String should have at least 1 character')
        }
        s.messages.push({ id: uid(), role: 'expert', text, at: now() })
        let ideasAdded = 0
        let replyText: string

        const trigger = /^\/error\s+(\w+)/.exec(text.trim())
        const reportTrigger = /^\/report-(failed|missing)\s+(\w+)/.exec(text.trim())
        if (trigger) {
          armedError = trigger[1]
          replyText = `(Test mode) The next call will fail with \`${trigger[1]}\`.`
        } else if (reportTrigger) {
          if (reportTrigger[1] === 'failed') reportFailed = reportTrigger[2]
          else reportMissing = reportTrigger[2]
          replyText = `(Test mode) The next report will have part \`${reportTrigger[2]}\` ${reportTrigger[1]}.`
        } else if (text.trim() === '/finish-ready') {
          completeMap(s)
          rebuildRollups(s.profile)
          replyText = '(Test mode) The map is complete. Press *Finish and build my report*.'
        } else if (s.turn < SCRIPT.length) {
          const turn = SCRIPT[s.turn]
          if (s.proposals['process.name'] && s.turn === 3) delete s.proposals['process.name']
          turn.apply(s.profile)
          rebuildRollups(s.profile)
          s.proposingCluster = Boolean(turn.proposeCluster)
          if (turn.ideas) {
            for (const idea of IDEAS) {
              if (store.ideas.some((i) => i.fromSessionId === s.id && i.name === idea.name)) continue
              store.ideas.unshift({
                id: uid(),
                name: idea.name,
                words: idea.words,
                status: 'open',
                fromSessionId: s.id,
                startedSessionId: null,
                createdAt: now(),
              })
              ideasAdded += 1
            }
          }
          replyText = turn.reply(s.profile)
          s.turn += 1
        } else {
          replyText =
            'Your map is ready. Press *Finish and build my report* when you are happy, or tell me anything you want to correct.'
        }
        const reply = agent(replyText)
        s.messages.push(reply)
        const session = touched(s)
        return { reply: structuredClone(reply), session, ideasAdded }
      }),

    confirm: (id, target) =>
      call(() => {
        const s = writable(id)
        const p = s.profile.process
        if (target === 'substeps') {
          if (p.substeps.length === 0) throw new ApiError(422, 'invalid_value', 'There are no steps yet.')
          p.substep_count = p.substeps.length
          p.substeps_complete = true
        } else if (target === 'roles') {
          p.roles_confirmed = true
        } else {
          p.tools_confirmed = true
        }
        return touched(s)
      }),

    setCluster: (id, code) =>
      call(() => {
        const s = writable(id)
        const cluster = CLUSTERS.find((c) => c.code === code.toUpperCase())
        if (!cluster) throw new ApiError(422, 'unknown_cluster', 'This cluster code is not in the taxonomy.')
        s.profile.process.cluster = { code: cluster.code, name: cluster.name, decided_by: 'picker' }
        s.proposingCluster = false
        if (s.turn === 4) s.turn = 5
        return touched(s)
      }),

    close: (id) =>
      call(() => {
        const s = writable(id)
        s.status = 'no_candidate'
        s.finishedAt = now()
        s.proposingCluster = false
        return touched(s)
      }),

    finish: (id) =>
      call(() => {
        const s = writable(id)
        const out = toOut(s)
        if (!out.finish.ready) {
          throw new ApiError(409, 'map_incomplete', 'The map is not complete yet.', out.finish.blockedBy ?? 'below_gate')
        }
        s.status = 'finished'
        s.finishedAt = now()
        return touched(s)
      }),

    listIdeas: () => call(() => ({ ideas: structuredClone(store.ideas) })),

    startIdea: (id) => call(() => create(undefined, id)),

    deleteIdea: (id) =>
      call(() => {
        if (!store.ideas.some((i) => i.id === id)) throw new ApiError(404, 'not_found', NOT_FOUND)
        store.ideas = store.ideas.filter((i) => i.id !== id)
      }),

    deleteMyData: () =>
      call(() => {
        const counts = { sessions: store.sessions.length, ideas: store.ideas.length }
        store.sessions = []
        store.ideas = []
        return counts
      }),

    getTaxonomy: () => call(() => ({ clusters: structuredClone(CLUSTERS) })),

    getConfig: async () => {
      await wait()
      return { ...structuredClone(FAKE_CONFIG), workspaceOpen }
    },

    uploadDocument: async (id, file, onProgress) => {
      await call(() => {
        const s = writable(id)
        const limits = FAKE_CONFIG.documents
        if ((s.documents ?? []).length >= limits.maxFiles) {
          throw new ApiError(409, 'document_limit', `You can add up to ${limits.maxFiles} documents. Remove one to add another.`)
        }
        if (file.size > limits.maxFileMb * 1_048_576) {
          throw new ApiError(413, 'document_too_large', `This file is larger than ${limits.maxFileMb} MB.`)
        }
        if (file.size === 0) {
          throw new ApiError(422, 'document_unreadable', "I couldn't find any text in this file. If it is a scan, try the file it was made from.")
        }
        if (!limits.allowedTypes.includes(extOf(file.name))) {
          throw new ApiError(415, 'document_type', typeSentence(limits))
        }
      })
      for (const pct of [25, 50, 75, 100]) {
        await sleep(stepMs)
        onProgress?.(pct)
      }
      await sleep(readMs)
      return call((): DocumentUploadOut => {
        const s = writable(id)
        const lower = file.name.toLowerCase()
        if (lower.includes('scan')) {
          throw new ApiError(422, 'document_unreadable', "I couldn't find any text in this file. If it is a scan, try the file it was made from.")
        }
        if (lower.includes('inject')) {
          throw new ApiError(400, 'unsafe_input', "This document contains text that looks like instructions to the assistant, so I didn't read it.")
        }
        const docId = uid()
        const failed = lower.includes('failed')
        const read = failed ? { values: 0, steps: 0, truncated: false } : readDocument(s, docId, file.name)
        const record = {
          id: docId,
          name: file.name,
          kind: extOf(file.name),
          bytes: file.size,
          chars: failed ? 0 : 1000,
          truncated: read.truncated,
          uploadedAt: now(),
          outcome: (failed ? 'failed' : 'read') as DocumentOut['outcome'],
          proposals: read.values + read.steps + (extOf(file.name) === 'bpmn' && read.steps > 0 ? BPMN_LANES.length : 0),
        }
        ;(s.documents ??= []).push(record)
        let message = failed
          ? DOCUMENT_SENTENCES.failed
          : record.proposals === 0
            ? DOCUMENT_SENTENCES.nothingNew(file.name)
            : DOCUMENT_SENTENCES.read(file.name, read.values, read.steps)
        if (read.truncated) message += ` ${DOCUMENT_SENTENCES.truncated}`
        // The agent's question about the file (spec 14 §3.16), also the last message of the session.
        const reply: Message = {
          id: uid(),
          role: 'agent',
          text:
            failed || record.proposals === 0
              ? `${message} Let's carry on where we left off.`
              : `From "${file.name}" I'd fill the values marked as proposed in the panel.\nShould I fill it like this, or is something wrong?`,
          at: now(),
        }
        s.messages.push(reply)
        const session = touched(s)
        const document = session.documents.find((d) => d.id === docId)!
        const tally = { fields: read.values, steps: read.steps, cells: record.proposals - read.values - read.steps }
        return {
          session,
          document,
          report: {
            documentId: docId,
            outcome: record.outcome,
            reader: extOf(file.name) === 'bpmn' ? 'bpmn' : 'model',
            truncated: read.truncated,
            offered: tally,
            kept: tally,
            dropped: 0,
            skipped: [],
            stepList: 0,
            message,
            documentRole: failed ? null : 'whole_process',
            targetStep: null,
            targetSource: 'none',
            fromImage: ['png', 'jpg', 'jpeg'].includes(extOf(file.name)),
            conflicts: 0,
          },
          reply: structuredClone(reply),
        }
      })
    },

    removeDocument: (id, docId) =>
      call(() => {
        const s = writable(id)
        if (!(s.documents ?? []).some((d) => d.id === docId)) throw new ApiError(404, 'not_found', NOT_FOUND)
        s.documents = (s.documents ?? []).filter((d) => d.id !== docId)
        for (const [key, p] of Object.entries(s.docProposals ?? {})) {
          if (p.docId !== docId) continue
          clearValue(s.profile, key)
          delete s.docProposals![key]
        }
        dropEmptyRows(s.profile)
        return touched(s)
      }),

    confirmProposals: (id, keys) =>
      call(() => {
        const s = writable(id)
        for (const key of keys) {
          const p = s.docProposals?.[key]
          if (p) {
            ;(s.docConfirmed ??= {})[key] = p
            delete s.docProposals![key]
          }
          if (s.proposals[key] !== undefined) delete s.proposals[key]
        }
        return touched(s)
      }),

    rejectProposals: (id, keys) =>
      call(() => {
        const s = writable(id)
        for (const key of keys) {
          if (s.docProposals?.[key]) {
            clearValue(s.profile, key)
            delete s.docProposals[key]
          } else if (s.proposals[key] !== undefined) {
            clearValue(s.profile, key)
            delete s.proposals[key]
          }
        }
        return touched(s)
      }),

    getReport: (id) =>
      call(() => {
        const s = find(id)
        if (s.status !== 'finished') {
          throw new ApiError(409, 'report_not_ready', 'The report is ready once the map is finished.')
        }
        let report: DiscoveryReport = structuredClone(euReport)
        if (reportFailed) {
          const keys = reportFailed === 'steps' ? ['steps', 'route'] : [reportFailed]
          report = withFailedNote(report, keys as Array<'steps' | 'route'>)
          reportFailed = null
        }
        if (reportMissing && (PART_KEYS as readonly string[]).includes(reportMissing)) {
          delete (report as unknown as Record<string, unknown>)[reportMissing]
          reportMissing = null
        }
        return report
      }),

    getReportPdf: (id) =>
      call(() => {
        const s = find(id)
        if (s.status !== 'finished') {
          throw new ApiError(409, 'report_not_ready', 'The report is ready once the map is finished.')
        }
        return { blob: new Blob([FAKE_PDF], { type: 'application/pdf' }), filename: 'discovery-report-monthly-cost-review.pdf' }
      }),

    workspaceLogin: async (code, name) => {
      await wait()
      if (!name.trim() || name.length > 40) throw new ApiError(422, 'invalid_value', 'name: 1 to 40 characters')
      const match = workspaceOpen ? FAKE_CODES['demo-specialist'] : FAKE_CODES[code]
      if (!match) throw new ApiError(401, 'workspace_code_invalid', 'The access code is not valid.')
      return { token: match.token, role: match.role, name, expiresAt: new Date(Date.now() + 8 * 3_600_000).toISOString() }
    },

    reviewList: (filters) =>
      wsCall(() => {
        const triggered = workspaceTrigger(filters.q)
        const q = triggered ? '' : filters.q.trim().toLowerCase()
        if (q.length > 100) throw new ApiError(422, 'invalid_value', 'q: at most 100 characters')
        if (filters.status && !['active', 'finished', 'no_candidate'].includes(filters.status)) {
          throw new ApiError(422, 'invalid_value', 'status: not a known status')
        }
        const all = [...store.sessions]
          .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt) || a.id.localeCompare(b.id))
          .map(reviewRow)
        const rows = all.filter(
          (r) =>
            (!filters.status || r.status === filters.status) &&
            (!filters.cluster || r.clusterCode === filters.cluster) &&
            (!q || [r.processName, r.department, r.id].some((v) => v?.toLowerCase().includes(q))),
        )
        const count = (status: string) => all.filter((r) => r.status === status).length
        return {
          counts: { total: all.length, active: count('active'), finished: count('finished'), noCandidate: count('no_candidate') },
          rows,
          matching: rows.length,
          truncated: false,
        }
      }),

    reviewSession: (id) => wsCall(() => reviewSessionOut(find(id))),

    reviewConversation: (id) => wsCall(() => ({ sessionId: id, messages: structuredClone(find(id).messages) })),

    getReviewReportPdf: (id) =>
      wsCall(() => {
        if (find(id).status !== 'finished') {
          throw new ApiError(409, 'report_not_ready', 'The report is ready once the map is finished.')
        }
        return { blob: new Blob([FAKE_PDF], { type: 'application/pdf' }), filename: 'discovery-report-monthly-cost-review.pdf' }
      }),

    deleteReviewSession: (id, etag) =>
      wsCall(() => {
        if (workspaceOpen) throw new ApiError(403, 'forbidden', 'Deleting is switched off on this open demo.')
        const s = find(id)
        if (!etag) throw new ApiError(428, 'etag_required', 'This request needs the If-Match header.')
        if (etag !== `"e${s.etag ?? 1}"`) throw new ApiError(409, 'conflict', 'The session changed. Reload it and try again.')
        store.sessions = store.sessions.filter((x) => x.id !== id)
      }),
  }
}
