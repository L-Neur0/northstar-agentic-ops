/**
 * Tests for the Steps tabs and the **No further steps** button (spec 23 §3.8.9–10, §11.7, §11.8;
 * AC-23.33, AC-23.50, AC-23.51, AC-23.77, AC-23.78).
 * Why: the walk goes step by step; the tab shows `Step k (f/12)` from 1-based field views (S01–S11
 * and S13 scored, short step walk), the panel lists thirteen rows in registry order, S12 is
 * "(not scored)", an agent proposal reads "suggested from your answers", arrow keys move between tabs, and the expert can end the walk early.
 * Amended 2026-11-21 (spec 23 §3.6 rule 11, AC-23.150): a named step's tab reads `k · <name> (f/12)`,
 * cut with an ellipsis, the full name in `title` and `aria-label`; an unnamed one `Step k (f/12)`.
 * Amended 2026-11-21 (spec 23 §3.6 rule 12, AC-23.151): a step whose S14 view the server sends shows
 * a 14th row *Decision criteria*, "(not scored)", ✓ / ✎ when proposed, and its tab still counts f/12.
 * Rules: the button is enabled only with at least one row, an open walk, an active session and no
 * confirm in flight.
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { SubstepTabs } from './SubstepTabs'
import { emptyProfile, emptyStep, fullStep, stepViews, stepsSession, view, withProposals } from '../../test/fixtures/sessions'
import type { ProposalControls } from './ProposalActions'
import type { FieldView, SessionOut } from '../../types/process-discovery'

function Harness({ session, onNoFurther = vi.fn(), active = true, confirming = false }: {
  session: SessionOut
  onNoFurther?: () => void
  active?: boolean
  confirming?: boolean
}) {
  const [selected, setSelected] = useState(1)
  return (
    <SubstepTabs
      profile={session.profile}
      fieldViews={session.fieldViews}
      activeIndex={selected}
      onSelect={setSelected}
      sessionActive={active}
      confirming={confirming}
      onNoFurtherSteps={onNoFurther}
    />
  )
}

describe('SubstepTabs (AC-23.33)', () => {
  it('labels tabs from the 1-based views and shows the active step panel', () => {
    render(<Harness session={stepsSession()} />)
    expect(screen.getByRole('tab', { name: 'Step 1: Collect, 12 of 12 answered' })).toHaveAttribute('aria-selected', 'false')
    expect(screen.getByRole('tab', { name: 'Step 2: Consolidate, 5 of 12 answered' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tabpanel')).toHaveTextContent('Step 2 · Consolidate')
    expect(screen.getByText('(not scored)')).toBeInTheDocument()
    expect(screen.getByText('One view')).toBeInTheDocument()
  })

  it('shows the thirteen cell rows of the step in registry order, Rules or judgement after Hand-over', () => {
    render(<Harness session={stepsSession()} />)
    const rows = within(screen.getByRole('tabpanel')).getAllByRole('listitem')
    expect(rows).toHaveLength(13)
    expect(rows[11]).toHaveTextContent('Hand-over')
    expect(rows[11]).toHaveTextContent('(not scored)')
    expect(rows[12]).toHaveTextContent('Rules or judgement')
    expect(rows[12]).not.toHaveTextContent('(not scored)')
  })

  it('moves between tabs with the arrow keys (roving tabindex)', async () => {
    const user = userEvent.setup()
    render(<Harness session={stepsSession()} />)
    const tab2 = screen.getByRole('tab', { name: 'Step 2: Consolidate, 5 of 12 answered' })
    expect(tab2).toHaveAttribute('tabindex', '0')
    tab2.focus()
    await user.keyboard('{ArrowLeft}')
    const tab1 = screen.getByRole('tab', { name: 'Step 1: Collect, 12 of 12 answered' })
    expect(tab1).toHaveFocus()
    expect(tab1).toHaveAttribute('aria-selected', 'true')
    expect(tab2).toHaveAttribute('tabindex', '-1')
  })

  it('shows the step name on the tab, cut with an ellipsis, and Step k while unnamed (AC-23.150)', () => {
    const s = stepsSession()
    const long = 'Assess CVs and verify facts against the role requirements of the hiring manager'
    s.profile.process.substeps = [fullStep(long), emptyStep('')]
    render(<Harness session={s} />)
    const named = screen.getByRole('tab', { name: `Step 1: ${long}, 12 of 12 answered` })
    expect(named).toHaveAttribute('title', long)
    expect(named).toHaveTextContent(`1 · ${long} (12/12)`)
    expect(within(named).getByText(`1 · ${long}`)).toHaveClass('truncate')
    const unnamed = screen.getByRole('tab', { name: 'Step 2, 5 of 12 answered' })
    expect(unnamed).toHaveTextContent('Step 2 (5/12)')
  })

  it('says the steps appear later when there are no rows', () => {
    const s = stepsSession()
    s.profile = emptyProfile()
    s.fieldViews = []
    render(<Harness session={s} />)
    expect(screen.getByText('The steps appear here once you start describing them.')).toBeInTheDocument()
  })
})

describe('No further steps (AC-23.50, AC-23.51)', () => {
  it('is enabled with a row and an open walk, and calls the handler', async () => {
    const onNoFurther = vi.fn()
    render(<Harness session={stepsSession()} onNoFurther={onNoFurther} />)
    const button = screen.getByRole('button', { name: 'No further steps' })
    expect(button).toBeEnabled()
    expect(screen.getByText('Use this if the process has fewer steps than you said.')).toBeInTheDocument()
    await userEvent.click(button)
    expect(onNoFurther).toHaveBeenCalled()
  })

  it.each([
    ['no rows', (s: SessionOut) => ({ ...s, profile: emptyProfile(), fieldViews: [] }), true, false],
    ['walk complete', (s: SessionOut) => ({ ...s, profile: { ...s.profile, process: { ...s.profile.process, substeps_complete: true } } }), true, false],
    ['session closed', (s: SessionOut) => s, false, false],
    ['confirm in flight', (s: SessionOut) => s, true, true],
  ])('is disabled with %s', (_label, change, active, confirming) => {
    render(<Harness session={change(stepsSession())} active={active} confirming={confirming} />)
    expect(screen.getByRole('button', { name: 'No further steps' })).toBeDisabled()
  })

  it('works with one partial row', () => {
    const s = stepsSession()
    s.profile.process.substeps = [{ ...emptyStep('Only'), goal: 'x' }]
    s.fieldViews = stepViews(1, 2)
    render(<Harness session={s} />)
    expect(screen.getByRole('button', { name: 'No further steps' })).toBeEnabled()
    expect(fullStep('x').name).toBe('x')
  })
})

describe('proposals in steps (AC-23.77, AC-23.78)', () => {
  const controls = (over: Partial<ProposalControls> = {}): ProposalControls => ({
    canAct: true,
    disabled: false,
    pending: null,
    openQuotes: new Set(),
    onToggleQuote: vi.fn(),
    onConfirm: vi.fn(),
    onReject: vi.fn(),
    ...over,
  })
  const tabs = (proposals: ProposalControls, index = 1, session = withProposals()) =>
    render(
      <SubstepTabs
        profile={session.profile}
        fieldViews={session.fieldViews}
        activeIndex={index}
        onSelect={vi.fn()}
        sessionActive
        confirming={false}
        onNoFurtherSteps={vi.fn()}
        proposals={proposals}
      />,
    )

  it('✓ and ✎ on a cell use the 1-based cell key (AC-23.77)', async () => {
    const c = controls()
    tabs(c)
    await userEvent.click(screen.getByRole('button', { name: 'Confirm Goal' }))
    expect(c.onConfirm).toHaveBeenCalledWith(['process.substeps[2].goal'])
    await userEvent.click(screen.getByRole('button', { name: 'Reject Systems' }))
    expect(c.onReject).toHaveBeenCalledWith('process.substeps[2].systems', 'Systems')
  })

  it('a step with 2+ proposed cells offers one batch confirm with those keys in view order (AC-23.78)', async () => {
    const c = controls()
    tabs(c)
    await userEvent.click(screen.getByRole('button', { name: 'Confirm all 3 proposals in step 2' }))
    expect(c.onConfirm).toHaveBeenCalledWith(['process.substeps[2].name', 'process.substeps[2].goal', 'process.substeps[2].systems'])
  })

  it('no batch button with fewer than two proposals; tabs say "· proposed" in text', () => {
    tabs(controls(), 0)
    expect(screen.queryByRole('button', { name: /Confirm all/ })).not.toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /^Step 1\b.*, proposed$/ })).toHaveTextContent(/\(0\/12\) · proposed$/)
    expect(screen.getByRole('tab', { name: /^Step 2\b.*, proposed$/ })).toHaveTextContent(/· proposed$/)
  })

  it('the batch and ✓ / ✎ are disabled during another write', () => {
    tabs(controls({ disabled: true }))
    expect(screen.getByRole('button', { name: 'Confirm all 3 proposals in step 2' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Confirm Goal' })).toBeDisabled()
  })
})

describe('agent proposals in steps (AC-23.33, short step walk)', () => {
  it('an agent proposal shows "suggested from your answers" and the same ✓ / ✎ as a document one', async () => {
    const session = stepsSession()
    session.fieldViews = session.fieldViews.map((v) =>
      v.key === 'process.substeps[2].owner'
        ? view(v.key, 'proposed', { source: 'agent', quote: 'I own the merge myself' })
        : v,
    )
    const onConfirm = vi.fn()
    const onReject = vi.fn()
    render(
      <SubstepTabs
        profile={session.profile}
        fieldViews={session.fieldViews}
        activeIndex={1}
        onSelect={vi.fn()}
        sessionActive
        confirming={false}
        onNoFurtherSteps={vi.fn()}
        proposals={{ canAct: true, disabled: false, pending: null, openQuotes: new Set(), onToggleQuote: vi.fn(), onConfirm, onReject }}
      />,
    )
    const panel = screen.getByRole('tabpanel')
    expect(within(panel).getByText('Proposed · suggested from your answers')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Confirm Step owner' }))
    expect(onConfirm).toHaveBeenCalledWith(['process.substeps[2].owner'])
    await userEvent.click(screen.getByRole('button', { name: 'Reject Step owner' }))
    expect(onReject).toHaveBeenCalledWith('process.substeps[2].owner', 'Step owner')
  })
})

describe('a confirmed agent value (short step walk)', () => {
  it('keeps the chip "suggested from your answers" without ✓ / ✎, like a confirmed document value', () => {
    const session = stepsSession()
    session.fieldViews = session.fieldViews.map((v) =>
      v.key === 'process.substeps[2].goal' ? view(v.key, 'complete', { source: 'agent' }) : v,
    )
    render(<Harness session={session} />)
    const panel = screen.getByRole('tabpanel')
    expect(within(panel).getByText('suggested from your answers')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Confirm Goal' })).not.toBeInTheDocument()
  })
})

describe('SubstepTabs open-conflict marker (AC-23.146)', () => {
  it('marks a step cell with an open conflict in the step panel', () => {
    const session = stepsSession()
    session.fieldViews = session.fieldViews.map((v) =>
      v.key === 'process.substeps[2].goal' ? view(v.key, 'complete', { conflict: 'open' }) : v,
    )
    render(<Harness session={session} />)
    const panel = screen.getByRole('tabpanel')
    expect(panel).toHaveTextContent('Conflict – answer in the chat')
    expect(screen.getAllByText('Conflict – answer in the chat')).toHaveLength(1)
  })
})

describe('the S14 decision criteria row (AC-23.151)', () => {
  function judgementSession(s14: FieldView) {
    const s = stepsSession()
    s.profile.process.substeps[1] = {
      ...s.profile.process.substeps[1],
      decision_type: { kind: 'judgement', evidence: 'I decide which variances need a reason' },
      decision_criteria: { basis: 'the 5 % threshold', set_by: 'Head of controlling', written: 'no', varies: '' },
    }
    s.fieldViews = [...s.fieldViews, s14]
    return s
  }

  it('shows Decision criteria after Rules or judgement, not scored, and keeps the tab at f/12', () => {
    render(<Harness session={judgementSession(view('process.substeps[2].decision_criteria', 'complete'))} />)
    const rows = within(screen.getByRole('tabpanel')).getAllByRole('listitem')
    expect(rows).toHaveLength(14)
    expect(rows[12]).toHaveTextContent('Rules or judgement')
    expect(rows[13]).toHaveTextContent('Decision criteria')
    expect(rows[13]).toHaveTextContent('(not scored)')
    expect(rows[13]).toHaveTextContent('Based on: the 5 % threshold; set by Head of controlling; not written down')
    expect(screen.getByRole('tab', { name: 'Step 2: Consolidate, 5 of 12 answered' })).toBeInTheDocument()
  })

  it('offers ✓ / ✎ on a proposed S14, like the other optional rows', async () => {
    const s = judgementSession(view('process.substeps[2].decision_criteria', 'proposed', { source: 'agent', quote: 'my call' }))
    const onConfirm = vi.fn()
    render(
      <SubstepTabs
        profile={s.profile}
        fieldViews={s.fieldViews}
        activeIndex={1}
        onSelect={vi.fn()}
        sessionActive
        confirming={false}
        onNoFurtherSteps={vi.fn()}
        proposals={{ canAct: true, disabled: false, pending: null, openQuotes: new Set(), onToggleQuote: vi.fn(), onConfirm, onReject: vi.fn() }}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Confirm Decision criteria' }))
    expect(onConfirm).toHaveBeenCalledWith(['process.substeps[2].decision_criteria'])
  })

  it('shows thirteen rows for a step the server sends no S14 view for (rules or unknown)', () => {
    render(<Harness session={stepsSession()} />)
    expect(within(screen.getByRole('tabpanel')).getAllByRole('listitem')).toHaveLength(13)
    expect(screen.queryByText('Decision criteria')).not.toBeInTheDocument()
  })
})
