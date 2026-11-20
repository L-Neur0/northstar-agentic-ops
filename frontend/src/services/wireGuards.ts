/**
 * Runtime checks of the wire shapes in `types/process-discovery.ts` and `types/report.ts` (spec 15
 * part 2 §3.4, spec 23 §3.12.6, §12; AC-23.5, AC-23.59, AC-23.97).
 * Why: TypeScript types vanish at run time, so a drift between the backend's wire models and this
 * mirror would only show as a broken screen. These checks let the contract tests prove that real
 * recorded responses, and the fake API's responses, have exactly the shape the screens read.
 * What: one `check<Type>(value)` per response, each returning the list of problems (empty = valid),
 * with the path of every wrong field. Must not: repair data, decide anything about the interview,
 * or be called on the hot path of the app (the server is trusted; this is a test aid). The one
exception is `loadReport`, which the report page uses to treat a broken part as missing.
 * Part 3 (spec 23 §20): `checkReviewListOut`, `checkReviewSessionOut` and `checkConversationOut`
 * mirror spec 21 §4.2, checked against the recorded `review-*.json` samples.
 */
import { PHASE_ORDER } from '../types/process-discovery'
import { PART_KEYS, type LoadedReport } from '../types/report'

type Check = (value: unknown, path: string, problems: string[]) => void

const PHASES = [...PHASE_ORDER, 'finished', 'no_candidate']
const STATUSES = ['active', 'finished', 'no_candidate']
const FIELD_STATUSES = ['complete', 'partial', 'invalid', 'proposed', 'skipped', 'empty', 'deferred', 'given_up']
const FINISH_BLOCKS = ['below_gate', 'substeps_incomplete', 'roles_not_confirmed', 'tools_not_confirmed']

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)

const prim =
  (type: 'string' | 'number' | 'boolean'): Check =>
  (v, path, problems) => {
    if (typeof v !== type) problems.push(`${path}: expected ${type}`)
  }
const str = prim('string')
const num = prim('number')
const bool = prim('boolean')
const oneOf =
  (values: readonly unknown[]): Check =>
  (v, path, problems) => {
    if (!values.includes(v)) problems.push(`${path}: ${JSON.stringify(v)} is not one of ${values.join(', ')}`)
  }
const nullable =
  (inner: Check): Check =>
  (v, path, problems) => {
    if (v !== null) inner(v, path, problems)
  }
const arrayOf =
  (inner: Check): Check =>
  (v, path, problems) => {
    if (!Array.isArray(v)) problems.push(`${path}: expected array`)
    else v.forEach((item, i) => inner(item, `${path}[${i}]`, problems))
  }
const shape =
  (fields: Record<string, Check>): Check =>
  (v, path, problems) => {
    if (!isObject(v)) {
      problems.push(`${path}: expected object`)
      return
    }
    for (const [key, check] of Object.entries(fields)) {
      if (!(key in v)) problems.push(`${path}.${key}: missing`)
      else check(v[key], `${path}.${key}`, problems)
    }
  }
const object: Check = (v, path, problems) => {
  if (!isObject(v)) problems.push(`${path}: expected object`)
}

const message = shape({ id: str, role: oneOf(['expert', 'agent']), text: str, at: str })
const cluster = shape({ code: str, name: str, description: str })

const fieldView = shape({
  key: str,
  id: str,
  label: str,
  phase: oneOf(PHASES),
  status: oneOf(FIELD_STATUSES),
  reason: str,
  missing: arrayOf(str),
  source: nullable(oneOf(['expert', 'document', 'specialist'])),
  quote: nullable(str),
  documentName: nullable(str),
  asks: num,
})

const process = shape({
  name: str,
  cluster: shape({ code: str, name: str, decided_by: str }),
  trigger: str,
  end_result: str,
  value_at_end: str,
  business_pain: str,
  volume: shape({ count: nullable(num), period: str, raw: str }),
  process_owner: shape({ role: str, none_identified: bool }),
  baseline_metric: shape({ value: str, unit: str, qualitative: str, estimated: bool }),
  target_metric: shape({ value: str, unit: str }),
  variation: shape({ same: str, differences: str }),
  sensitive_data: arrayOf(object),
  substep_count: nullable(num),
  substep_count_rejected: nullable(num),
  substeps: arrayOf(
    shape({
      name: str,
      goal: str,
      activities: arrayOf(str),
      roles: arrayOf(object),
      owner: str,
      systems: arrayOf(str),
      data: shape({ inputs: arrayOf(str), outputs: arrayOf(str) }),
      effort: shape({ duration: str, frequency: str }),
      pain_points: arrayOf(str),
      approvals: arrayOf(object),
      exceptions: arrayOf(object),
      handover: str,
    }),
  ),
  all_roles: arrayOf(str),
  all_tools: arrayOf(str),
  substeps_complete: bool,
  roles_confirmed: bool,
  tools_confirmed: bool,
})

const documentOut = shape({
  id: str,
  name: str,
  kind: str,
  bytes: num,
  chars: num,
  truncated: bool,
  uploadedAt: str,
  outcome: oneOf(['read', 'failed']),
  proposals: num,
  pending: num,
})

const sessionOut = shape({
  id: str,
  status: oneOf(STATUSES),
  phase: oneOf(PHASES),
  displayName: nullable(str),
  createdAt: str,
  updatedAt: str,
  finishedAt: nullable(str),
  messages: arrayOf(message),
  profile: shape({ department: str, user_function: str, region: str, process }),
  fieldViews: arrayOf(fieldView),
  score: shape({ value: num, filledPoints: num, totalPoints: num }),
  finish: shape({ ready: bool, blockedBy: nullable(oneOf(FINISH_BLOCKS)), looksLikeTask: bool }),
  scope: nullable(shape({ verdict: str, widened: bool })),
  clusterProposal: nullable(cluster),
  reportStatus: nullable(oneOf(['mapped', 'validated'])),
  documents: arrayOf(documentOut),
})

const tally = shape({ fields: num, steps: num, cells: num })
const documentReport = shape({
  documentId: str,
  outcome: oneOf(['read', 'failed']),
  reader: oneOf(['model', 'bpmn']),
  truncated: bool,
  offered: tally,
  kept: tally,
  dropped: num,
  skipped: arrayOf(shape({ key: str, reason: str, items: nullable(num) })),
  stepList: num,
  message: str,
  documentRole: nullable(str),
  targetStep: nullable(num),
  targetSource: oneOf(['document', 'expert', 'focus', 'none']),
  fromImage: bool,
})

/* ---- the discovery report (types/report.ts) ---- */

const NOTE_KINDS = ['missing', 'failed', 'empty', 'simplified', 'incomplete', 'task', 'one_off', 'error']
const note = shape({ kind: oneOf(NOTE_KINDS), text: str })
const part = (fields: Record<string, Check>) => shape({ number: num, title: str, note: nullable(note), ...fields })
const reportField = shape({ key: str, label: str, value: str, status: nullable(oneOf(FIELD_STATUSES)), source: nullable(str), quote: nullable(str) })
const diagram = shape({
  lanes: arrayOf(str),
  nodes: arrayOf(shape({ id: str, type: str, label: str, lane: str, stepIndex: nullable(num), marker: str })),
  flows: arrayOf(shape({ source: str, target: str, label: str, isDefault: bool })),
  dataObjects: arrayOf(shape({ id: str, stepIndex: num, direction: oneOf(['input', 'output']), label: str })),
  dataStores: arrayOf(shape({ id: str, label: str, steps: arrayOf(num) })),
  simplified: bool,
})

const REPORT_PARTS: Record<string, Check> = {
  atAGlance: part({
    hours: str,
    routeHeadline: nullable(str),
    top: arrayOf(shape({ id: str, title: str, stepsLabel: str, hours: str })),
    prepare: arrayOf(str),
  }),
  process: part({ fields: arrayOf(reportField), notes: arrayOf(note) }),
  measures: part({ fields: arrayOf(reportField), notes: arrayOf(note) }),
  map: part({
    diagram: nullable(diagram),
    processName: str,
    caption: nullable(str),
    systems: arrayOf(str),
    columns: arrayOf(shape({ number: num, name: str, cells: arrayOf(reportField) })),
    rowLabels: arrayOf(str),
  }),
  steps: part({
    rows: arrayOf(
      shape({
        number: num,
        name: str,
        hours: str,
        fit: nullable(str),
        fitLabel: str,
        routeId: nullable(str),
        routeName: str,
        routeReason: str,
        reason: str,
        evidence: str,
        evidenceLabel: str,
      }),
    ),
    catalogueNote: nullable(str),
  }),
  route: part({
    headline: str,
    groups: arrayOf(shape({ key: str, title: str, items: arrayOf(shape({ number: num, name: str, hours: str, routeName: str, reason: str })) })),
    prepare: arrayOf(str),
    catalogueNote: nullable(str),
  }),
  assessment: part({
    summary: str,
    opportunities: arrayOf(
      shape({
        id: str,
        title: str,
        stepsLabel: str,
        typeLabel: str,
        whatChanges: str,
        how: str,
        prepareFirst: str,
        impact: str,
        impactReason: str,
        feasibility: str,
        feasibilityReason: str,
        evidence: str,
        evidenceLabel: str,
        review: nullable(str),
      }),
    ),
    stayHuman: arrayOf(shape({ stepsLabel: str, reason: str, evidence: str })),
  }),
  potential: part({
    complete: bool,
    steps: arrayOf(shape({ number: num, name: str, hoursPerRun: str, runsPerYear: str, hoursPerYear: str })),
    opportunities: arrayOf(shape({ id: str, title: str, stepsLabel: str, stepHours: str })),
    totals: shape({ hours: str }),
    formulas: arrayOf(str),
    assumptions: arrayOf(str),
    problems: arrayOf(str),
    parkedLine: str,
  }),
  readiness: part({
    dimensions: arrayOf(
      shape({ key: str, label: str, question: str, level: str, levelLabel: str, reason: str, toPrepare: str, note: str }),
    ),
    footer: str,
  }),
  path: part({
    groups: arrayOf(
      shape({
        key: str,
        title: str,
        prepareLines: arrayOf(str),
        items: arrayOf(shape({ opportunityId: str, title: str, stepsLabel: str, stepHours: str })),
        emptyText: nullable(str),
      }),
    ),
  }),
  gaps: part({ fields: arrayOf(reportField), documents: arrayOf(shape({ name: str, outcome: str })), closingNote: str }),
}

const cover = shape({
  productName: str,
  companyName: str,
  processName: str,
  department: str,
  cluster: str,
  region: str,
  owner: str,
  date: str,
  status: str,
})

const report = shape({ cover, ...REPORT_PARTS, generatedAt: str })

const summary = shape({
  id: str,
  status: oneOf(STATUSES),
  phase: oneOf(PHASES),
  processName: nullable(str),
  clusterCode: nullable(str),
  score: num,
  messageCount: num,
  createdAt: str,
  updatedAt: str,
  reportStatus: nullable(str),
})

const idea = shape({
  id: str,
  name: str,
  words: str,
  status: oneOf(['open', 'started', 'dismissed']),
  fromSessionId: str,
  startedSessionId: nullable(str),
  createdAt: str,
})

const errorBody: Check = (v, path, problems) => {
  shape({ code: str, message: str })(v, path, problems)
  if (isObject(v) && 'reason' in v) str(v.reason, `${path}.reason`, problems)
}

const run = (check: Check) => (value: unknown) => {
  const problems: string[] = []
  check(value, '$', problems)
  return problems
}

export const checkSessionOut = run(sessionOut)
export const checkTurnOut = run(shape({ reply: message, session: sessionOut, ideasAdded: num }))
export const checkSessionList = run(shape({ sessions: arrayOf(summary) }))
export const checkIdeaList = run(shape({ ideas: arrayOf(idea) }))
export const checkTaxonomy = run(shape({ clusters: arrayOf(cluster) }))
export const checkPublicConfig = run(
  shape({
    productName: str,
    regions: arrayOf(str),
    languages: arrayOf(str),
    documents: shape({ allowedTypes: arrayOf(str), maxFiles: num, maxFileMb: num, maxImageMb: num }),
    workspaceOpen: bool,
  }),
)
export const checkApiErrorBody = run(errorBody)
export const checkDocumentUploadOut = run(
  shape({ session: sessionOut, document: documentOut, report: documentReport, reply: message }),
)
export const checkDocumentList = run(shape({ documents: arrayOf(documentOut) }))
export const checkDiscoveryReport = run(report)

/**
 * The report as the page holds it (spec 23 §11.11.3, §12): the cover and each part are kept only
 * when they pass their guard; a part that is absent, null or of the wrong shape becomes null and
 * is shown as "could not be generated", never as a page error.
 */
const reviewRow = shape({
  id: str,
  createdAt: str,
  updatedAt: str,
  processName: nullable(str),
  department: nullable(str),
  clusterCode: nullable(str),
  clusterName: nullable(str),
  region: nullable(str),
  status: oneOf(STATUSES),
  phase: oneOf(PHASES),
  fieldsFilled: num,
  fieldsTotal: num,
  steps: num,
  messageCount: num,
  documentCount: num,
})
const reviewList = shape({
  counts: shape({ total: num, active: num, finished: num, noCandidate: num }),
  rows: arrayOf(reviewRow),
  matching: num,
  truncated: bool,
})
const stepGrid = shape({
  stepNames: arrayOf(str),
  rows: arrayOf(shape({ key: str, id: str, label: str, cells: arrayOf(shape({ value: str, source: nullable(str), status: nullable(str) })) })),
})
const reviewSession = shape({
  id: str,
  etag: str,
  summary: shape({
    department: nullable(str),
    function: nullable(str),
    region: nullable(str),
    processName: nullable(str),
    clusterName: nullable(str),
    status: oneOf(STATUSES),
    phase: oneOf(PHASES),
    fieldsFilled: num,
    fieldsTotal: num,
    stepsStarted: num,
    stepsExpected: num,
    completeness: num,
    filledPoints: num,
    totalPoints: num,
    messageCount: num,
    documentCount: num,
  }),
  steps: stepGrid,
  rawSteps: nullable(stepGrid),
  documents: arrayOf(shape({ name: str, kind: str, bytes: num, uploadedAt: str, outcome: oneOf(['read', 'failed']) })),
  report: nullable(report),
})

export const checkReviewListOut = run(reviewList)
export const checkReviewSessionOut = run(reviewSession)
export const checkConversationOut = run(shape({ sessionId: str, messages: arrayOf(message) }))

export function loadReport(value: unknown): LoadedReport {
  const data = isObject(value) ? value : {}
  const keep = (key: string, check: Check) => {
    if (!(key in data) || data[key] === null) return null
    const problems: string[] = []
    check(data[key], key, problems)
    return problems.length === 0 ? data[key] : null
  }
  const loaded: Record<string, unknown> = {
    cover: keep('cover', cover),
    generatedAt: typeof data.generatedAt === 'string' ? data.generatedAt : '',
  }
  for (const key of PART_KEYS) loaded[key] = keep(key, REPORT_PARTS[key])
  return loaded as LoadedReport
}
