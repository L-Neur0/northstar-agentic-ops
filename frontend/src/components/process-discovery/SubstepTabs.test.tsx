/**
 * Tests for the Steps tabs and the **No further steps** button (spec 23 §3.8.9–10, §11.7, §11.8;
 * AC-23.33, AC-23.50, AC-23.51, AC-23.77, AC-23.78).
 * Why: the walk goes step by step; the tab shows `Step k (f/11)` from 1-based field views, S12 is
 * "(not scored)", arrow keys move between tabs, and the expert can end the walk early.
 * Rules: the button is enabled only with at least one row, an open walk, an active session and no
 * confirm in flight.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { SubstepTabs } from './SubstepTabs'
import { emptyProfile, emptyStep, fullStep, stepViews, stepsSession, view, withProposals } from '../../test/fixtures/sessions'
import type { ProposalControls } from './ProposalActions'
import type { SessionOut } from '../../types/process-discovery'

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
    expect(screen.getByRole('tab', { name: 'Step 1 (11/11)' })).toHaveAttribute('aria-selected', 'false')
    expect(screen.getByRole('tab', { name: 'Step 2 (5/11)' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tabpanel')).toHaveTextContent('Step 2 · Consolidate')
    expect(screen.getByText('(not scored)')).toBeInTheDocument()
    expect(screen.getByText('One view')).toBeInTheDocument()
  })

  it('moves between tabs with the arrow keys (roving tabindex)', async () => {
    const user = userEvent.setup()
    render(<Harness session={stepsSession()} />)
    const tab2 = screen.getByRole('tab', { name: 'Step 2 (5/11)' })
    expect(tab2).toHaveAttribute('tabindex', '0')
    tab2.focus()
    await user.keyboard('{ArrowLeft}')
    const tab1 = screen.getByRole('tab', { name: 'Step 1 (11/11)' })
    expect(tab1).toHaveFocus()
    expect(tab1).toHaveAttribute('aria-selected', 'true')
    expect(tab2).toHaveAttribute('tabindex', '-1')
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
    expect(screen.getByRole('tab', { name: /^Step 1 \(0\/11\) · proposed$/ })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /^Step 2 .* · proposed$/ })).toBeInTheDocument()
  })

  it('the batch and ✓ / ✎ are disabled during another write', () => {
    tabs(controls({ disabled: true }))
    expect(screen.getByRole('button', { name: 'Confirm all 3 proposals in step 2' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Confirm Goal' })).toBeDisabled()
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
