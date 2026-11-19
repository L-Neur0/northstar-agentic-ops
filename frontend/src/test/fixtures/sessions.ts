/**
 * Hand-made `SessionOut` fixtures for the interview-side tests, one builder per phase (spec 23 §7).
 * Why: component and page tests need realistic server responses without a backend; the shapes are
 * the wire contract of spec 15 §3.4, so a contract change breaks these at compile time.
 * Rules: fixtures only describe what the server would send; they hold no scoring logic beyond
 * what is needed to make a view consistent. Must not be imported by application code.
 */
import type {
  FieldStatus,
  FieldView,
  Phase,
  Profile,
  SessionOut,
  SessionSummary,
  Step,
} from '../../types/process-discovery'

export function emptyProfile(): Profile {
  return {
    department: '',
    user_function: '',
    region: '',
    process: {
      name: '',
      cluster: { code: '', name: '', decided_by: '' },
      trigger: '',
      end_result: '',
      value_at_end: '',
      business_pain: '',
      volume: { count: null, period: '', raw: '' },
      process_owner: { role: '', none_identified: false },
      baseline_metric: { value: '', unit: '', qualitative: '', estimated: false },
      target_metric: { value: '', unit: '' },
      variation: { same: '', differences: '' },
      sensitive_data: [],
      substep_count: null,
      substep_count_rejected: null,
      substeps: [],
      all_roles: [],
      all_tools: [],
      substeps_complete: false,
      roles_confirmed: false,
      tools_confirmed: false,
    },
  }
}

export function emptyStep(name = ''): Step {
  return {
    name,
    goal: '',
    activities: [],
    roles: [],
    owner: '',
    systems: [],
    data: { inputs: [], outputs: [] },
    effort: { duration: '', frequency: '' },
    pain_points: [],
    approvals: [],
    exceptions: [],
    handover: '',
  }
}

export function fullStep(name: string): Step {
  return {
    name,
    goal: `Goal of ${name}`,
    activities: ['Collect', 'Check'],
    roles: [{ role: 'Cost controller', contribution: 'prepares' }],
    owner: 'Cost controller',
    systems: ['SAP'],
    data: { inputs: ['Ledger'], outputs: ['Report'] },
    effort: { duration: '2 hours', frequency: 'monthly' },
    pain_points: ['Manual copy'],
    approvals: [{ none: true }],
    exceptions: [{ none: true }],
    handover: 'Sent to the head of controlling',
  }
}

const P_FIELDS: Array<[string, string, string, Phase]> = [
  ['department', 'P01', 'Department', 'context'],
  ['user_function', 'P02', 'Role', 'context'],
  ['region', 'P03', 'Region', 'context'],
  ['process.name', 'P04', 'Process name', 'find'],
  ['process.cluster', 'P05', 'Cluster', 'find'],
  ['process.trigger', 'P06', 'Trigger', 'boundaries'],
  ['process.end_result', 'P07', 'End result', 'boundaries'],
  ['process.value_at_end', 'P08', 'Who uses the result', 'boundaries'],
  ['process.business_pain', 'P09', 'Business pain', 'boundaries'],
  ['process.volume', 'P10', 'Volume', 'measure'],
  ['process.process_owner', 'P11', 'Process owner', 'measure'],
  ['process.baseline_metric', 'P12', 'Time today', 'measure'],
  ['process.target_metric', 'P13', 'Target', 'measure'],
  ['process.variation', 'P14', 'Same way everywhere', 'measure'],
  ['process.sensitive_data', 'P15', 'Sensitive data or regulation', 'measure'],
  ['process.substep_count', 'P16', 'Number of main steps', 'step_count'],
]

const S_FIELDS: Array<[string, string, string]> = [
  ['name', 'S01', 'Step name'],
  ['goal', 'S02', 'Goal'],
  ['activities', 'S03', 'Activities'],
  ['roles', 'S04', 'Roles involved'],
  ['owner', 'S05', 'Step owner'],
  ['systems', 'S06', 'Systems'],
  ['data', 'S07', 'Data in and out'],
  ['effort', 'S08', 'Effort'],
  ['pain_points', 'S09', 'Pain points'],
  ['approvals', 'S10', 'Approvals'],
  ['exceptions', 'S11', 'Exceptions'],
  ['handover', 'S12', 'Hand-over'],
]

export function view(key: string, status: FieldStatus = 'empty', extra: Partial<FieldView> = {}): FieldView {
  const p = P_FIELDS.find(([k]) => k === key)
  const cell = /^process\.substeps\[(\d+)\]\.(\w+)$/.exec(key)
  const s = cell ? S_FIELDS.find(([leaf]) => leaf === cell[2]) : undefined
  const label = p?.[2] ?? s?.[2] ?? key
  return {
    key,
    id: p?.[1] ?? s?.[1] ?? '?',
    label,
    phase: p?.[3] ?? 'steps',
    status,
    reason: status === 'complete' ? '' : `${label} has not been answered yet.`,
    missing: [],
    source: status === 'complete' || status === 'proposed' ? 'expert' : null,
    quote: null,
    documentName: null,
    asks: 0,
    ...extra,
  }
}

/** Field views for every P field, with the given statuses (default `empty`). */
export function processViews(statuses: Record<string, FieldStatus> = {}): FieldView[] {
  return P_FIELDS.map(([key]) => view(key, statuses[key] ?? 'empty'))
}

/** Field views for step k (1-based), `completeCount` first cells complete. */
export function stepViews(k: number, completeCount: number, overrides: Record<string, FieldStatus> = {}): FieldView[] {
  return S_FIELDS.map(([leaf], i) => {
    const key = `process.substeps[${k}].${leaf}`
    return view(key, overrides[leaf] ?? (i < completeCount ? 'complete' : 'empty'))
  })
}

export function buildSession(overrides: Partial<SessionOut> = {}): SessionOut {
  return {
    id: 's-1',
    status: 'active',
    phase: 'context',
    displayName: null,
    createdAt: '2026-11-19T08:00:00Z',
    updatedAt: '2026-11-19T08:00:00Z',
    finishedAt: null,
    messages: [{ id: 'm-1', role: 'agent', text: 'Welcome. Which department do you work in?', at: '2026-11-19T08:00:00Z' }],
    profile: emptyProfile(),
    fieldViews: processViews(),
    score: { value: 0, filledPoints: 0, totalPoints: 18 },
    finish: { ready: false, blockedBy: 'below_gate', looksLikeTask: false },
    scope: null,
    clusterProposal: null,
    reportStatus: null,
    ...overrides,
  }
}

const ALL_P_COMPLETE = Object.fromEntries(P_FIELDS.map(([k]) => [k, 'complete' as FieldStatus]))

/** A session on phase `steps` with P16 = 4, step 1 complete and step 2 half done. */
export function stepsSession(overrides: Partial<SessionOut> = {}): SessionOut {
  const profile = emptyProfile()
  profile.department = 'Finance control'
  profile.process.name = 'Monthly cost review'
  profile.process.substep_count = 4
  profile.process.substeps = [fullStep('Collect'), { ...emptyStep('Consolidate'), goal: 'One view' }]
  return buildSession({
    phase: 'steps',
    profile,
    fieldViews: [...processViews(ALL_P_COMPLETE), ...stepViews(1, 12), ...stepViews(2, 5)],
    score: { value: 0.65, filledPoints: 40, totalPoints: 62 },
    finish: { ready: false, blockedBy: 'below_gate', looksLikeTask: false },
    ...overrides,
  })
}

/** A complete map, ready to finish. */
export function readySession(overrides: Partial<SessionOut> = {}): SessionOut {
  const profile = emptyProfile()
  profile.process.name = 'Monthly cost review'
  profile.process.substep_count = 2
  profile.process.substeps = [fullStep('Collect'), fullStep('Report')]
  profile.process.all_roles = ['Cost controller']
  profile.process.all_tools = ['SAP']
  profile.process.substeps_complete = true
  profile.process.roles_confirmed = true
  profile.process.tools_confirmed = true
  return buildSession({
    phase: 'review',
    profile,
    fieldViews: [...processViews(ALL_P_COMPLETE), ...stepViews(1, 12), ...stepViews(2, 12)],
    score: { value: 1, filledPoints: 40, totalPoints: 40 },
    finish: { ready: true, blockedBy: null, looksLikeTask: false },
    ...overrides,
  })
}

export function summary(overrides: Partial<SessionSummary> = {}): SessionSummary {
  return {
    id: 's-1',
    status: 'active',
    phase: 'measure',
    processName: null,
    clusterCode: null,
    score: 0.31,
    messageCount: 12,
    createdAt: '2026-11-18T08:00:00Z',
    updatedAt: '2026-11-18T08:00:00Z',
    reportStatus: null,
    ...overrides,
  }
}
