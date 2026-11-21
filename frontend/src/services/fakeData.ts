/**
 * Static data of the fake API: the field registry labels, the NIG taxonomy and the scripted
 * monthly cost review (spec 23 §3.12.4; spec 12 §3.4, §3.8).
 * Why: the fake must return the same shapes as spec 15 with believable content, so the screens
 * can be built and demoed before the backend exists.
 * Rules: used only by `fakeApi.ts`, which is loaded by dynamic import in fake mode and never ends
 * up in a production bundle (AC-23.48). Must not be imported by real client code.
 */
import type { ClusterRef, Phase, Profile, Step } from '../types/process-discovery'

export interface FieldDef {
  key: string
  id: string
  label: string
  phase: Phase
  weight: number
}

export const PROCESS_FIELDS: FieldDef[] = [
  { key: 'department', id: 'P01', label: 'Department', phase: 'context', weight: 1 },
  { key: 'user_function', id: 'P02', label: 'Role', phase: 'context', weight: 1 },
  { key: 'region', id: 'P03', label: 'Region', phase: 'context', weight: 1 },
  { key: 'process.name', id: 'P04', label: 'Process name', phase: 'find', weight: 1 },
  { key: 'process.cluster', id: 'P05', label: 'Cluster', phase: 'find', weight: 1 },
  { key: 'process.trigger', id: 'P06', label: 'Trigger', phase: 'boundaries', weight: 1 },
  { key: 'process.end_result', id: 'P07', label: 'End result', phase: 'boundaries', weight: 1 },
  { key: 'process.value_at_end', id: 'P08', label: 'Who uses the result', phase: 'boundaries', weight: 1 },
  { key: 'process.business_pain', id: 'P09', label: 'Business pain', phase: 'boundaries', weight: 1 },
  { key: 'process.volume', id: 'P10', label: 'Volume', phase: 'measure', weight: 1 },
  { key: 'process.process_owner', id: 'P11', label: 'Process owner', phase: 'measure', weight: 1 },
  { key: 'process.baseline_metric', id: 'P12', label: 'Time today', phase: 'measure', weight: 2 },
  { key: 'process.target_metric', id: 'P13', label: 'Target', phase: 'measure', weight: 2 },
  { key: 'process.variation', id: 'P14', label: 'Same way everywhere', phase: 'measure', weight: 1 },
  { key: 'process.sensitive_data', id: 'P15', label: 'Sensitive data or regulation', phase: 'measure', weight: 1 },
  { key: 'process.substep_count', id: 'P16', label: 'Number of main steps', phase: 'step_count', weight: 1 },
]

export const STEP_FIELDS: Array<{ leaf: keyof Step; id: string; label: string; weight: number }> = [
  { leaf: 'name', id: 'S01', label: 'Step name', weight: 1 },
  { leaf: 'goal', id: 'S02', label: 'Goal', weight: 1 },
  { leaf: 'activities', id: 'S03', label: 'Activities', weight: 1 },
  { leaf: 'roles', id: 'S04', label: 'Roles involved', weight: 1 },
  { leaf: 'owner', id: 'S05', label: 'Step owner', weight: 1 },
  { leaf: 'systems', id: 'S06', label: 'Systems', weight: 1 },
  { leaf: 'data', id: 'S07', label: 'Data in and out', weight: 1 },
  { leaf: 'effort', id: 'S08', label: 'Effort', weight: 1 },
  { leaf: 'pain_points', id: 'S09', label: 'Pain points', weight: 1 },
  { leaf: 'approvals', id: 'S10', label: 'Approvals', weight: 1 },
  { leaf: 'exceptions', id: 'S11', label: 'Exceptions', weight: 1 },
  { leaf: 'handover', id: 'S12', label: 'Hand-over', weight: 0 },
  { leaf: 'decision_type', id: 'S13', label: 'Rules or judgement', weight: 1 },
  { leaf: 'decision_criteria', id: 'S14', label: 'Decision criteria', weight: 0 },
]

/** S14 applies only to a judgement or mix step (spec 12 §3.13 `field_applies`; AC-23.151). */
export const stepFieldApplies = (leaf: keyof Step, step: Step): boolean =>
  leaf !== 'decision_criteria' || ['judgement', 'mix'].includes(step.decision_type.kind.trim().toLowerCase())

export const CLUSTERS: ClusterRef[] = [
  { code: 'FIN', name: 'Finance', description: 'Planning, recording and reporting money - budgets, invoices, costs and the monthly close.' },
  { code: 'HR', name: 'People & HR', description: 'Hiring, paying and developing employees, from the first offer to the last working day.' },
  { code: 'LEG', name: 'Legal', description: 'Contracts, legal advice, disputes and keeping the company within the law.' },
  { code: 'IT', name: 'IT & Security', description: 'Running laptops, accounts, software and networks, and keeping them safe from attack.' },
  { code: 'PRO', name: 'Procurement', description: 'Buying goods and services - choosing suppliers, ordering and receiving what was bought.' },
  { code: 'COM', name: 'Comms & Growth', description: "Telling the company's story inside and outside - press, internal news, the brand and the website." },
  { code: 'KNW', name: 'Knowledge & Ops', description: 'Running day-to-day operations and keeping procedures, project records and lessons learned usable.' },
  { code: 'ANL', name: 'Analytics & Strategy', description: 'Turning data into decisions - dashboards, analyses, business cases and the strategy plan.' },
  { code: 'GWT', name: 'Sales & Marketing', description: 'Finding and winning customers - leads, offers, bids, campaigns and the customer relationship.' },
]

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

export function emptyStep(): Step {
  return {
    name: '',
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
    decision_type: { kind: '', evidence: '' },
    decision_criteria: { basis: '', set_by: '', written: '', varies: '' },
  }
}

export const COST_REVIEW_STEPS: Step[] = [
  {
    name: 'Collect cost data',
    goal: 'All cost centre figures in one place',
    activities: ['Export actuals from SAP', 'Collect the site reports'],
    roles: [{ role: 'Cost controller', contribution: 'collects the figures' }],
    owner: 'Cost controller',
    systems: ['SAP', 'Excel'],
    data: { inputs: ['Cost centre actuals', 'Site reports'], outputs: ['Raw cost file'] },
    effort: { duration: '1 day', frequency: 'monthly' },
    pain_points: ['Site reports arrive late'],
    approvals: [{ none: true }],
    exceptions: [{ none: true }],
    handover: 'Raw cost file goes to consolidation',
    decision_type: { kind: 'rules', evidence: 'I always take the same SAP export' },
    decision_criteria: { basis: '', set_by: '', written: '', varies: '' },
  },
  {
    name: 'Consolidate',
    goal: 'One view per cluster',
    activities: ['Map cost centres to clusters', 'Merge the files'],
    roles: [{ role: 'Cost controller', contribution: 'merges the files' }],
    owner: 'Cost controller',
    systems: ['Excel'],
    data: { inputs: ['Raw cost file'], outputs: ['Consolidated view'] },
    effort: { duration: '1 day', frequency: 'monthly' },
    pain_points: ['Manual copy and paste'],
    approvals: [{ none: true }],
    exceptions: [{ description: 'Figures do not add up', loops_back_to: 1 }],
    handover: 'Consolidated view goes to analysis',
    decision_type: { kind: 'rules', evidence: 'Every cost centre maps to one cluster' },
    decision_criteria: { basis: '', set_by: '', written: '', varies: '' },
  },
  {
    name: 'Analyse variances',
    goal: 'Explain every variance above 5 %',
    activities: ['Compare with budget', 'Ask the sites for reasons'],
    roles: [
      { role: 'Cost controller', contribution: 'explains the variances' },
      { role: 'Site manager', contribution: 'answers questions' },
    ],
    owner: 'Cost controller',
    systems: ['Excel', 'Email'],
    data: { inputs: ['Consolidated view', 'Budget'], outputs: ['Variance comments'] },
    effort: { duration: '4 hours', frequency: 'monthly' },
    pain_points: ['Chasing answers by email'],
    approvals: [{ none: true }],
    exceptions: [{ none: true }],
    handover: 'Comments go into the review pack',
    decision_type: { kind: 'judgement', evidence: 'I decide which variances need a reason' },
    decision_criteria: { basis: 'Variances above 5 % of budget', set_by: 'Head of controlling', written: 'no', varies: 'How much detail each site gives' },
  },
  {
    name: 'Review and sign off',
    goal: 'Management agrees the month',
    activities: ['Build the review pack', 'Present to management'],
    roles: [{ role: 'Head of controlling', contribution: 'approves the pack' }],
    owner: 'Head of controlling',
    systems: ['PowerPoint'],
    data: { inputs: ['Variance comments'], outputs: ['Signed-off cost review'] },
    effort: { duration: '2 hours', frequency: 'monthly' },
    pain_points: ['Last-minute changes'],
    approvals: [{ approver_role: 'Head of controlling', waiting_time: '2 days' }],
    exceptions: [{ description: 'Questions from management', loops_back_to: 3 }],
    handover: '',
    decision_type: { kind: 'mix', evidence: 'Management mostly follows the pack, sometimes asks more' },
    decision_criteria: { basis: 'Whether the pack explains every large variance', set_by: '', written: 'partly', varies: '' },
  },
]

export const IDEAS = [
  { name: 'Chasing site managers', words: 'I chase the site managers for their numbers every Friday' },
  { name: 'Booking travel', words: 'I also book the travel for the whole team' },
]

/** One scripted turn: what it writes, and the agent's next question. */
export interface ScriptTurn {
  apply: (p: Profile) => void
  reply: (p: Profile) => string
  ideas?: boolean
  proposeCluster?: boolean
}

const step = (i: number, part?: 'first' | 'rest') => (p: Profile) => {
  const full = COST_REVIEW_STEPS[i]
  const rows = p.process.substeps
  while (rows.length <= i) rows.push(emptyStep())
  if (part === 'first') {
    rows[i] = { ...rows[i], name: full.name, goal: full.goal, activities: full.activities }
  } else {
    rows[i] = structuredClone(full)
  }
}

export const SCRIPT: ScriptTurn[] = [
  { apply: (p) => (p.department = 'Finance control'), reply: () => 'Thanks. **What is your role** in Finance control?' },
  {
    apply: (p) => (p.user_function = 'Cost controller'),
    reply: () => '**Which region** do you work in: North America, Europe, Middle East or Asia-Pacific?',
  },
  {
    apply: (p) => (p.region = 'Europe'),
    reply: () => "Let's find a process worth mapping. **Walk me through a typical month:** which tasks take most of your time?",
  },
  {
    apply: (p) => {
      if (!p.process.name) p.process.name = 'Monthly cost review'
    },
    ideas: true,
    proposeCluster: true,
    reply: (p) =>
      'I heard three things:\n\n1. the **' +
      p.process.name.toLowerCase() +
      '**\n2. chasing site managers for their numbers\n3. booking travel for the team\n\n' +
      `Let's map the ${p.process.name.toLowerCase()}. I kept the other two as ideas on *My processes*.\n\n` +
      'It sounds like it belongs to **Finance (FIN)**: planning, recording and reporting money. Is that right?',
  },
  {
    apply: (p) => (p.process.cluster = { code: 'FIN', name: 'Finance', decided_by: 'proposal' }),
    reply: () => 'Good, Finance it is. **What starts the monthly cost review?**',
  },
  { apply: (p) => (p.process.trigger = 'The ledger closes on the third working day'), reply: () => '**What is the end result** when it is done?' },
  { apply: (p) => (p.process.end_result = 'A signed-off cost report per cluster'), reply: () => '**Who uses that result?**' },
  { apply: (p) => (p.process.value_at_end = 'The management team'), reply: () => '**What hurts most** about it today?' },
  {
    apply: (p) => (p.process.business_pain = 'Three days of copying numbers by hand'),
    reply: () => 'Now a few numbers. **How often does it run?**',
  },
  { apply: (p) => (p.process.volume = { count: 1, period: 'month', raw: '' }), reply: () => '**Who owns the process?** A role, not a name.' },
  {
    apply: (p) => (p.process.process_owner = { role: 'Head of controlling', none_identified: false }),
    reply: () => '**How long does it take today**, roughly?',
  },
  {
    apply: (p) => (p.process.baseline_metric = { value: '3', unit: 'days', qualitative: '', estimated: true }),
    reply: () => '**What would good look like?** A target in days, like the time today.',
  },
  { apply: (p) => (p.process.target_metric = { value: '1', unit: 'days' }), reply: () => '**Is it done the same way in every region?**' },
  {
    apply: (p) => (p.process.variation = { same: 'partly', differences: 'Two regions use their own template' }),
    reply: () => '**Does it touch personal or sensitive data**, or a named regulation?',
  },
  { apply: (p) => (p.process.sensitive_data = [{ none: true }]), reply: () => '**How many main steps** does it have? Between 2 and 6.' },
  {
    apply: (p) => (p.process.substep_count = 4),
    reply: () => "Four steps. Let's walk them one at a time.\n\n**Step 1: what is it called, and what is its goal?**",
  },
  { apply: step(0, 'first'), reply: () => '**Who is involved** in step 1, which **systems** do you use, and how long does it take?' },
  { apply: step(0), reply: () => 'Step 1 is done. **Tell me about step 2**, the consolidation.' },
  { apply: step(1), reply: () => '**Step 3:** what happens when you analyse the variances?' },
  { apply: step(2), reply: () => 'And **step 4**, the review and sign-off?' },
  {
    apply: (p) => {
      step(3)(p)
      p.process.substeps_complete = true
    },
    reply: (p) =>
      'All four steps are described. Please **confirm the roles and systems** I collected (on the right, or say yes here):\n\n' +
      `- Roles: ${p.process.all_roles.join(', ')}\n- Systems: ${p.process.all_tools.join(', ')}`,
  },
  {
    apply: (p) => {
      p.process.roles_confirmed = true
      p.process.tools_confirmed = true
    },
    reply: () => 'Thank you. **Your map is complete.** Press *Finish and build my report* when you are happy with it.',
  },
]

/* ---- Documents (spec 23 §11.15.3): what the fake "reads" from a procedure or a BPMN file ---- */

export const FAKE_CONFIG = {
  productName: 'AI Use Case Discovery Agent',
  regions: ['North America', 'Europe', 'Middle East', 'Asia-Pacific'],
  languages: ['en', 'de'],
  documents: { allowedTypes: ['pdf', 'docx', 'xlsx', 'csv', 'txt', 'md', 'bpmn', 'xml'], maxFiles: 5, maxFileMb: 10, maxImageMb: 5 },
  workspaceOpen: false,
}

/** Process fields a procedure proposes, with the value and the quote it was read from. */
export const PROCEDURE_FIELDS: Array<{ key: 'trigger' | 'end_result'; value: string; quote: string }> = [
  {
    key: 'trigger',
    value: 'Month-end close completed',
    quote: 'The review starts once month-end close is completed.',
  },
  {
    key: 'end_result',
    value: 'Monthly cost report with variance comments',
    quote: 'The process ends with the monthly cost report, including a comment for every variance.',
  },
]

/** Step names a procedure (or a BPMN file) proposes, each with its quote. */
export const PROCEDURE_STEPS: Array<{ name: string; quote: string }> = [
  { name: 'Export actuals', quote: 'Step 1: export actual costs per cost centre from the ledger.' },
  { name: 'Compare with budget', quote: 'Step 2: compare actuals with the budget in the workbook.' },
  { name: 'Collect explanations', quote: 'Step 3: cost centre managers explain flagged variances.' },
  { name: 'Review', quote: 'Step 4: the head of controlling reviews and approves the commentary.' },
  { name: 'Send the cost report', quote: 'Step 5: publish the cost report for the management team.' },
]

/** Roles a BPMN file proposes from its lanes (on step 1 and step 2). */
export const BPMN_LANES = ['Cost controller', 'Cost centre manager']

/** Spec 17 §3.12 and §3.7 sentences, built by the fake like the server builds them. */
export const DOCUMENT_SENTENCES = {
  read: (name: string, values: number, steps: number) =>
    `I read "${name}" and found ${values} values${steps > 0 ? ` and ${steps} steps` : ''} for your process. Nothing counts until you confirm it.`,
  nothingNew: (name: string) => `I read "${name}" but found nothing new for the form.`,
  truncated: 'It is long, so I read only the first part.',
  failed: "I couldn't read this document just now. The interview continues without it; you can remove it and try again.",
}

/** A tiny valid PDF for the fake download. */
export const FAKE_PDF = '%PDF-1.4\n1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n2 0 obj << /Type /Pages /Kids [] /Count 0 >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n'

/* ---- Workspace seed (spec 23 §19.10.3; AC-23.139): five sessions for the specialist's list ---- */

export interface WorkspaceSeedSession {
  id: string
  status: 'active' | 'finished' | 'no_candidate'
  /** How the profile is filled: the whole cost review, two of its steps, the context only, or nothing. */
  fill: 'complete' | 'steps' | 'context' | 'empty'
  updatedHoursAgo: number
  createdDaysAgo: number
  processName?: string
  department?: string
  clusterCode?: string
  /** Keep a first version of the steps that differs from the current one (step 2 name and one cell). */
  rawSteps?: boolean
  documents?: Array<{ name: string; kind: string; bytes: number; outcome: 'read' | 'failed' }>
  /** Expert answers after the welcome, each with the agent's next line ('' = no reply yet). Empty: the script. */
  conversation: Array<[expert: string, agent: string]>
}

/** The expert's side of the scripted cost review, one answer per script turn (first 14 turns). */
export const COST_REVIEW_ANSWERS = [
  'Finance control',
  'Cost controller',
  'Europe',
  'Mostly the monthly cost review, chasing site managers for their numbers, and booking travel for the team.',
  'Yes, Finance.',
  'The ledger closes on the third working day.',
  'A signed-off cost report per cluster.',
  'The management team.',
  'Three days of copying numbers by hand.',
  'Once a month.',
  'The head of controlling.',
  'About three days.',
  'One day would be good.',
  'Partly. Two regions use their own template.',
]

export const WORKSPACE_SEED: WorkspaceSeedSession[] = [
  {
    id: 'seed-cost-review',
    status: 'finished',
    fill: 'complete',
    updatedHoursAgo: 2,
    createdDaysAgo: 3,
    rawSteps: true,
    documents: [
      { name: 'cost-review-procedure.pdf', kind: 'pdf', bytes: 18_432, outcome: 'read' },
      { name: 'old-template.xlsx', kind: 'xlsx', bytes: 9_216, outcome: 'failed' },
    ],
    conversation: [],
  },
  {
    id: 'seed-invoice-check',
    status: 'finished',
    fill: 'complete',
    updatedHoursAgo: 26,
    createdDaysAgo: 4,
    processName: 'Supplier invoice check',
    department: 'Procurement',
    clusterCode: 'PRO',
    conversation: [
      ['Procurement', 'Thanks. **What is your role** in Procurement?'],
      ['Buyer', "Let's find a process worth mapping. **Which task takes most of your time?**"],
      ['Checking supplier invoices against the orders.', '**What starts the check?**'],
      ['An invoice arrives in the shared mailbox.', 'Good. **What is the end result?**'],
    ],
  },
  {
    id: 'seed-onboarding',
    status: 'active',
    fill: 'steps',
    updatedHoursAgo: 5,
    createdDaysAgo: 1,
    processName: 'Laptop onboarding',
    department: 'IT operations',
    clusterCode: 'IT',
    conversation: [
      ['IT operations', 'Thanks. **What is your role** in IT operations?'],
      ['Service desk lead', "Let's find a process worth mapping. **Which task takes most of your time?**"],
      ['Preparing laptops for new joiners.', '**How many main steps** does it have?'],
      ['Four.', "Four steps. **Step 1: what is it called?**"],
      ['Order the laptop.', '**Step 2?**'],
    ],
  },
  {
    id: 'seed-unnamed',
    status: 'active',
    fill: 'context',
    updatedHoursAgo: 0.2,
    createdDaysAgo: 0,
    department: 'Legal',
    conversation: [
      ['Legal', 'Thanks. **What is your role** in Legal?'],
      ['Contract lawyer', ''],
    ],
  },
  {
    id: 'seed-ended',
    status: 'no_candidate',
    fill: 'context',
    updatedHoursAgo: 72,
    createdDaysAgo: 5,
    department: 'Communications',
    conversation: [
      ['Communications', 'Thanks. **What is your role** in Communications?'],
      ['Editor', "Let's find a process worth mapping. **Which task takes most of your time?**"],
      ['Nothing repeats, every article is different.', 'Understood. There is no process to map today, so I have closed this session.'],
    ],
  },
]
