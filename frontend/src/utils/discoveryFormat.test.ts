/**
 * Tests for the display formatters of the interview side (spec 23 §3.8.8, AC-23.30).
 * Why: values reach the panel only through `formatValue`, so every kind of the registry and both
 * none sentinels need a case; phase labels and relative time are shared by Home and the dialogs.
 * Rules: the formatter reads the profile by field key and never grades a value.
 */
import { emptyProfile, emptyStep, fullStep } from '../test/fixtures/sessions'
import { completenessPct, formatRelativeTime, formatValue, phaseLabel, sessionStatusText } from './discoveryFormat'
import { summary } from '../test/fixtures/sessions'

describe('formatValue (AC-23.30)', () => {
  const profile = emptyProfile()
  profile.department = 'Finance control'
  profile.process.cluster = { code: 'FIN', name: 'Finance', decided_by: 'proposal' }
  profile.process.volume = { count: 1, period: 'month', raw: '' }
  profile.process.process_owner = { role: 'Head of controlling', none_identified: false }
  profile.process.baseline_metric = { value: '3', unit: 'days', qualitative: '', estimated: true }
  profile.process.target_metric = { value: '2', unit: 'days' }
  profile.process.variation = { same: 'partly', differences: 'Two regions differ' }
  profile.process.sensitive_data = [{ item: 'Salaries', detail: 'personal data' }]
  profile.process.substep_count = 4
  profile.process.substeps = [
    { ...fullStep('Collect'), exceptions: [{ description: 'Numbers missing', loops_back_to: 1 }], approvals: [{ approver_role: 'CFO', waiting_time: '2 days' }] },
  ]

  it.each([
    ['department', 'Finance control'],
    ['process.cluster', 'Finance (FIN)'],
    ['process.volume', '1 per month'],
    ['process.process_owner', 'Head of controlling'],
    ['process.baseline_metric', '3 days (estimated)'],
    ['process.target_metric', '2 days'],
    ['process.variation', 'Partly: Two regions differ'],
    ['process.sensitive_data', 'Salaries (personal data)'],
    ['process.substep_count', '4'],
    ['process.substeps[1].activities', 'Collect, Check'],
    ['process.substeps[1].roles', 'Cost controller – prepares'],
    ['process.substeps[1].approvals', 'CFO (2 days)'],
    ['process.substeps[1].exceptions', 'Numbers missing → back to step 1'],
    ['process.substeps[1].data', 'in: Ledger · out: Report'],
    ['process.substeps[1].effort', '2 hours · monthly'],
    ['process.substeps[1].decision_type', 'Rules: The same checks every month'],
  ])('formats %s as "%s"', (key, expected) => {
    expect(formatValue(profile, key)).toBe(expected)
  })

  it('shows "None" for a none row and for an owner with none_identified', () => {
    const p = emptyProfile()
    p.process.sensitive_data = [{ none: true }]
    p.process.process_owner = { role: '', none_identified: true }
    p.process.substeps = [{ ...fullStep('A'), approvals: [{ none: true }] }]
    expect(formatValue(p, 'process.sensitive_data')).toBe('None')
    expect(formatValue(p, 'process.process_owner')).toBe('None')
    expect(formatValue(p, 'process.substeps[1].approvals')).toBe('None')
  })

  it('falls back to raw volume and qualitative time, and Yes / No variation', () => {
    const p = emptyProfile()
    p.process.volume = { count: null, period: '', raw: 'a few hundred a month' }
    p.process.baseline_metric = { value: '', unit: '', qualitative: 'most of the first week', estimated: false }
    p.process.variation = { same: 'yes', differences: '' }
    expect(formatValue(p, 'process.volume')).toBe('a few hundred a month')
    expect(formatValue(p, 'process.baseline_metric')).toBe('most of the first week')
    expect(formatValue(p, 'process.variation')).toBe('Yes')
    p.process.variation = { same: 'no', differences: 'Each site' }
    expect(formatValue(p, 'process.variation')).toBe('No: Each site')
  })

  it('words the S13 kind (rules, judgement, a mix) and shows an empty one as empty (short step walk)', () => {
    const p = emptyProfile()
    p.process.substeps = [{ ...fullStep('A'), decision_type: { kind: 'mix', evidence: 'mostly rules' } }, emptyStep('B')]
    expect(formatValue(p, 'process.substeps[1].decision_type')).toBe('A mix: mostly rules')
    expect(formatValue(p, 'process.substeps[2].decision_type')).toBe('')
  })

  it('words S14 as "Based on: …; set by …; not written down; varies: …" and an empty one as empty (AC-23.151)', () => {
    const p = emptyProfile()
    p.process.substeps = [
      { ...fullStep('A'), decision_criteria: { basis: 'the threshold', set_by: 'Head of controlling', written: 'no', varies: 'by site' } },
      { ...fullStep('B'), decision_criteria: { basis: 'experience', set_by: '', written: 'Partly', varies: '' } },
      emptyStep('C'),
    ]
    expect(formatValue(p, 'process.substeps[1].decision_criteria')).toBe('Based on: the threshold; set by Head of controlling; not written down; varies: by site')
    expect(formatValue(p, 'process.substeps[2].decision_criteria')).toBe('Based on: experience; partly written down')
    expect(formatValue(p, 'process.substeps[3].decision_criteria')).toBe('')
  })

  it('returns an empty string for empty values and unknown keys', () => {
    const p = emptyProfile()
    expect(formatValue(p, 'department')).toBe('')
    expect(formatValue(p, 'process.volume')).toBe('')
    expect(formatValue(p, 'process.substeps[3].name')).toBe('')
    expect(formatValue(p, 'nothing.here')).toBe('')
  })
})

describe('phaseLabel, status text and time', () => {
  it('labels every phase, including the two endings', () => {
    expect(phaseLabel('context')).toBe('About you')
    expect(phaseLabel('step_count')).toBe('Step count')
    expect(phaseLabel('finished')).toBe('Finished')
    expect(phaseLabel('no_candidate')).toBe('Ended')
  })

  it('words the session status by status and report status (AC-23.7)', () => {
    expect(sessionStatusText(summary({ status: 'active', phase: 'measure' }))).toBe('In progress · Measures')
    expect(sessionStatusText(summary({ status: 'finished', reportStatus: 'mapped' }))).toBe('Mapped')
    expect(sessionStatusText(summary({ status: 'finished', reportStatus: 'validated' }))).toBe('Mapped · Validated by IT')
    expect(sessionStatusText(summary({ status: 'no_candidate' }))).toBe('Ended · nothing to map')
  })

  it('rounds the completeness from the server score', () => {
    expect(completenessPct(0.645)).toBe(65)
    expect(completenessPct(0)).toBe(0)
  })

  it('gives coarse relative times', () => {
    const now = Date.parse('2026-11-19T12:00:00Z')
    expect(formatRelativeTime('2026-11-19T11:59:40Z', now)).toBe('just now')
    expect(formatRelativeTime('2026-11-19T11:55:00Z', now)).toBe('5 minutes ago')
    expect(formatRelativeTime('2026-11-19T10:00:00Z', now)).toBe('2 hours ago')
    expect(formatRelativeTime('2026-11-18T10:00:00Z', now)).toBe('yesterday')
    expect(formatRelativeTime('2026-11-16T10:00:00Z', now)).toBe('3 days ago')
    expect(formatRelativeTime('not a date', now)).toBe('')
  })
})
