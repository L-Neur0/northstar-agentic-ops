/**
 * Tests for the "Your process" panel and its *Finish* block (spec 23 §3.8.1, §3.8.12;
 * AC-23.38, AC-23.39).
 * Why: the *Finish* button state comes only from the server's `finish.ready`; `looksLikeTask` is
 * advice and never blocks; a blocked button explains why, linked by `aria-describedby`.
 * Rules: an unknown blocked-reason code is shown as is, never hidden.
 */
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ProcessProfilePanel } from './ProcessProfilePanel'
import { defaultSections } from './sectionState'
import { renderWithProviders } from '../../test/render'
import { buildSession, readySession } from '../../test/fixtures/sessions'
import { initialDiscoveryState } from '../../hooks/discoveryReducer'
import type { SessionOut } from '../../types/process-discovery'

function panel(session: SessionOut, over: Partial<Parameters<typeof ProcessProfilePanel>[0]> = {}) {
  const onFinish = vi.fn()
  renderWithProviders(
    <ProcessProfilePanel
      session={session}
      sections={defaultSections()}
      onToggleSection={vi.fn()}
      activeStep={0}
      onSelectStep={vi.fn()}
      pending={initialDiscoveryState.pending}
      locked={false}
      onConfirm={vi.fn()}
      onPickCluster={vi.fn()}
      onFinish={onFinish}
      {...over}
    />,
  )
  return onFinish
}

const finishButton = () => screen.getByRole('button', { name: /Finish and build my report/ })

describe('ProcessProfilePanel (AC-23.38)', () => {
  it('is an aside labelled Your process with the sections in order', () => {
    panel(buildSession())
    const aside = screen.getByRole('complementary', { name: 'Your process' })
    expect(aside).toHaveTextContent(/About you.*The process.*Boundaries.*Measures.*Number of steps.*Steps.*Roles and systems/s)
  })

  it('enables Finish when ready and active, with the closing sentence', async () => {
    const onFinish = panel(readySession())
    expect(finishButton()).toBeEnabled()
    expect(screen.getByText('After this, the session is closed.')).toBeInTheDocument()
    await userEvent.click(finishButton())
    expect(onFinish).toHaveBeenCalled()
  })

  it('looksLikeTask shows the note and does not disable Finish', () => {
    panel(readySession({ finish: { ready: true, blockedBy: null, looksLikeTask: true } }))
    expect(screen.getByText(/This looks like a single task rather than a process/)).toBeInTheDocument()
    expect(finishButton()).toBeEnabled()
  })

  it('shows the building state while finishing', () => {
    panel(readySession(), { pending: { ...initialDiscoveryState.pending, finishing: true } })
    expect(screen.getByRole('button', { name: /Building your report…/ })).toBeDisabled()
  })

  it('shows Open my report when finished and nothing for no_candidate', () => {
    panel(readySession({ status: 'finished', phase: 'finished' }))
    expect(screen.getByRole('link', { name: 'Open my report' })).toHaveAttribute('href', '/report/s-1')
  })

  it('shows no Finish block for no_candidate', () => {
    panel(buildSession({ status: 'no_candidate', phase: 'no_candidate' }))
    expect(screen.queryByRole('button', { name: /Finish and build my report/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Open my report' })).not.toBeInTheDocument()
  })
})

describe('blocked reasons (AC-23.39)', () => {
  it.each([
    ['below_gate', 'Your map is 65 % complete. It needs 80 % to finish.'],
    ['substeps_incomplete', 'Some steps are not fully described yet.'],
    ['roles_not_confirmed', 'Please confirm the list of roles.'],
    ['tools_not_confirmed', 'Please confirm the list of systems.'],
    ['something_new', 'something_new'],
  ])('%s → "%s", linked by aria-describedby', (code, sentence) => {
    panel(buildSession({ score: { value: 0.65, filledPoints: 40, totalPoints: 62 }, finish: { ready: false, blockedBy: code, looksLikeTask: false } }))
    const button = finishButton()
    expect(button).toBeDisabled()
    const reason = screen.getByText(sentence)
    expect(button).toHaveAttribute('aria-describedby', reason.id)
  })

  it('is disabled when ready but the session is locked', () => {
    panel(readySession(), { locked: true })
    expect(finishButton()).toBeDisabled()
  })
})
