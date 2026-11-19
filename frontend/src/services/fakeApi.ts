/**
 * In-memory fake of the interview routes of spec 15 part 2 (spec 23 §3.12.4–5; AC-23.47).
 * Why: the screens are built, tested and demoed before the backend is ready. The fake implements
 * the same `DiscoveryApi` as the HTTP client, plays a scripted monthly cost review, and keeps the
 * server's rules (closed sessions, the *Finish* gate, unknown clusters, ideas started once).
 * Rules: only the fake builds field views, scores and *Finish* state; real client code never does.
 * It is loaded by dynamic import in fake mode only and a production build refuses fake mode
 * (AC-23.48). Manual triggers: `/error <code>` fails the next call, `/finish-ready` completes the map.
 */
import { ApiError, type DiscoveryApi } from './api'
import {
  CLUSTERS,
  COST_REVIEW_STEPS,
  IDEAS,
  PROCESS_FIELDS,
  SCRIPT,
  STEP_FIELDS,
  emptyProfile,
} from './fakeData'
import { getValue } from '../utils/discoveryFormat'
import type {
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

const ERROR_STATUS: Record<string, number> = {
  session_closed: 400,
  unsafe_input: 400,
  not_found: 404,
  map_incomplete: 409,
  conflict: 409,
  unknown_cluster: 422,
  validation_error: 422,
  rate_limited: 429,
  budget_exhausted: 429,
  model_unavailable: 503,
  visitor_key_required: 401,
  network: 0,
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
): FieldView {
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
    makeView(f.key, f.id, f.label, f.phase, getValue(s.profile, f.key), s.proposals[f.key]),
  )
  s.profile.process.substeps.forEach((_, i) => {
    for (const f of STEP_FIELDS) {
      const key = `process.substeps[${i + 1}].${f.leaf}`
      views.push(makeView(key, f.id, f.label, 'steps', getValue(s.profile, key), undefined))
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
  })
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
        ERROR_STATUS[code] ?? 400,
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
    if (!s) throw new ApiError(404, 'not_found', 'This session could not be found.')
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
      if (!idea) throw new ApiError(404, 'not_found', 'This idea could not be found.')
      if (idea.status === 'started') throw new ApiError(409, 'conflict', 'This idea has already been started.')
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
          throw new ApiError(422, 'validation_error', 'The message must be 1 to 16,000 characters.')
        }
        s.messages.push({ id: uid(), role: 'expert', text, at: now() })
        let ideasAdded = 0
        let replyText: string

        const trigger = /^\/error\s+(\w+)/.exec(text.trim())
        if (trigger) {
          armedError = trigger[1]
          replyText = `(Test mode) The next call will fail with \`${trigger[1]}\`.`
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
          if (p.substeps.length === 0) throw new ApiError(422, 'validation_error', 'There are no steps yet.')
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
        if (!cluster) throw new ApiError(422, 'unknown_cluster', 'That cluster is not known.')
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
        if (!store.ideas.some((i) => i.id === id)) throw new ApiError(404, 'not_found', 'This idea could not be found.')
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
  }
}
