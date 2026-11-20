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
 */
import { ApiError, type DiscoveryApi } from './api'
import {
  BPMN_LANES,
  CLUSTERS,
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
  emptyProfile,
  emptyStep,
} from './fakeData'
import { euReport, withFailedNote } from '../test/fixtures/report'
import { getValue } from '../utils/discoveryFormat'
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
}

interface Store {
  sessions: FakeSession[]
  ideas: Idea[]
}

export interface FakeApiOptions {
  /** Fixed delay, or a [min, max] range in ms. Default 300–800 ms to show spinners. */
  delayMs?: number | [number, number]
  /** Keep data in sessionStorage so a reload keeps it. Default true. */
  persist?: boolean
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

export function createFakeApi(options: FakeApiOptions = {}): DiscoveryApi {
  const persist = options.persist ?? true
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
        sessions: [...store.sessions].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)).map(toSummary),
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
      return structuredClone(FAKE_CONFIG)
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
  }
}
