/**
 * The interview page: chat on the left, "Your process" on the right, phase meter on top
 * (spec 23 §3.4–3.9; AC-23.14–23.16, 23.21–23.27, 23.32, 23.40, 23.41, 23.44, 23.45, 23.49).
 * Why: the Process Discovery page, styled with Tailwind: same header
 * actions, same layout (chat 60 %, panel up to 480 px), same honest exit, same first-visit intro
 * and welcome-back dialog; the Copilot prompt and analysis buttons are replaced by *Finish*.
 * Rules: server-derived state lives in `useDiscoveryState`; presentation state (open sections,
 * chosen step tab, two-press exit, intro, composer text) stays here and survives every response.
 * The two endings are told apart by `status`; "report ready" is never shown for `no_candidate`.
 * Must not compute completeness or decide a phase.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57).
 */
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, History, Info, Plus } from 'lucide-react'
import { AppHeader } from '../components/layout/AppHeader'
import { Alert } from '../components/ui/Alert'
import { Button } from '../components/ui/Button'
import { Spinner } from '../components/ui/Spinner'
import { ChatInput } from '../components/chat/ChatInput'
import { ChatMessageList } from '../components/chat/ChatMessageList'
import { DiscoveryPhaseMeter } from '../components/process-discovery/DiscoveryPhaseMeter'
import { ProcessProfilePanel } from '../components/process-discovery/ProcessProfilePanel'
import { ClusterPicker } from '../components/process-discovery/ClusterPicker'
import { DiscoverySessionsModal } from '../components/process-discovery/DiscoverySessionsModal'
import { DiscoveryIntroModal } from '../components/process-discovery/DiscoveryIntroModal'
import { hasSeenIntro, markIntroSeen } from '../components/process-discovery/introStorage'
import { applyPhase, defaultSections, toggleSection, type SectionStateMap } from '../components/process-discovery/sectionState'
import { useDiscoveryState } from '../hooks/useDiscoveryState'
import { activeStepIndex } from '../utils/substepProgress'
import type { Phase, SessionSummary } from '../types/process-discovery'

function HeaderAction({ label, icon, onClick }: { label: string; icon: React.ReactNode; onClick: () => void }) {
  return (
    <Button aria-label={label} icon={icon} onClick={onClick}>
      <span className="hidden sm:inline">{label}</span>
    </Button>
  )
}

export function ProcessDiscovery() {
  const { sessionId } = useParams<{ sessionId?: string }>()
  const navigate = useNavigate()
  const d = useDiscoveryState(sessionId)
  const { state } = d
  const session = state.session

  const [sections, setSections] = useState<SectionStateMap>(defaultSections)
  const [manualStep, setManualStep] = useState<number | null>(null)
  const [confirmingClose, setConfirmingClose] = useState(false)
  const [introOpen, setIntroOpen] = useState(() => !hasSeenIntro())
  const [composer, setComposer] = useState('')
  const [seen, setSeen] = useState<{ id: string; phase: Phase } | null>(null)

  // Derived from the server slice during render (React's "adjust state on prop change" pattern):
  // a new session resets the presentation state; a phase change runs the automatic section rules
  // and hands the step tab back to the walk.
  if (session && (seen?.id !== session.id || seen.phase !== session.phase)) {
    const sameSession = seen?.id === session.id
    setSeen({ id: session.id, phase: session.phase })
    setSections((prev) => applyPhase(sameSession ? prev : defaultSections(), session.phase, session))
    setManualStep(null)
    if (!sameSession) setConfirmingClose(false)
  }
  if (state.restoreText !== null) {
    setComposer(state.restoreText)
    d.restoreConsumed()
  }

  const rows = session?.profile.process.substeps.length ?? 0
  const walkStep = session ? activeStepIndex(session.fieldViews, rows) : 0
  const shownStep = manualStep ?? walkStep
  const active = session?.status === 'active' && !state.locked
  const composerDisabled = state.loading || state.pending.sending || state.locked || session?.status !== 'active'
  const messages = session ? (state.optimistic ? [...session.messages, state.optimistic] : session.messages) : []

  const dismissIntro = () => {
    markIntroSeen()
    setIntroOpen(false)
  }

  const openFromList = (s: SessionSummary) => {
    d.hidePastSessions()
    navigate(s.status === 'finished' ? `/report/${s.id}` : `/process-discovery/${s.id}`)
  }

  const send = (text: string) => {
    setComposer('')
    void d.sendMessage(text)
  }

  let statusLine: React.ReactNode = null
  if (session?.status === 'finished') {
    statusLine = (
      <span className="text-success">
        ✓ Map finished. Your report is ready.{' '}
        <Link to={`/report/${session.id}`} className="font-medium underline">
          Open report
        </Link>
      </span>
    )
  } else if (session?.status === 'no_candidate') {
    statusLine = 'Session ended: no process to map. Start a new one whenever you like.'
  } else if (state.locked) {
    statusLine = 'This session is closed.'
  } else if (state.ideasAdded > 0) {
    statusLine = `Kept ${state.ideasAdded} ${state.ideasAdded === 1 ? 'idea' : 'ideas'} on My processes.`
  }

  return (
    <div className="flex min-h-screen flex-col bg-surface lg:h-screen">
      <AppHeader
        actions={
          <>
            <HeaderAction label="How this works" icon={<Info className="h-4 w-4" aria-hidden="true" />} onClick={() => setIntroOpen(true)} />
            <HeaderAction label="Past sessions" icon={<History className="h-4 w-4" aria-hidden="true" />} onClick={() => void d.showPastSessions()} />
            <HeaderAction label="New" icon={<Plus className="h-4 w-4" aria-hidden="true" />} onClick={() => void d.createNew()} />
            <Link
              to="/"
              aria-label="My processes"
              className="inline-flex items-center gap-1.5 rounded-md border border-line-strong bg-surface px-3 py-1.5 text-sm font-medium text-fg hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
            >
              <ArrowLeft className="h-4 w-4" aria-hidden="true" />
              <span className="hidden sm:inline">My processes</span>
            </Link>
          </>
        }
      />

      {session && (
        <DiscoveryPhaseMeter
          phase={session.phase}
          score={session.score}
          substepCount={session.profile.process.substep_count}
          rows={rows}
          activeStep={shownStep}
        />
      )}

      {state.error && !state.initFailed && (
        <Alert tone="error" onClose={d.clearError}>
          {state.error}
        </Alert>
      )}

      <main data-testid="discovery-main" className="flex flex-1 flex-col lg:min-h-0 lg:flex-row">
        <section aria-label="Discovery conversation" className="flex h-[85vh] min-w-0 flex-col lg:h-auto lg:min-h-0 lg:flex-[3]">
          {state.loading ? (
            <div role="status" className="flex flex-1 items-center justify-center gap-2 text-sm text-muted">
              <Spinner /> Starting your session…
            </div>
          ) : state.initFailed ? (
            <div className="flex flex-1 items-center justify-center p-8">
              <div className="max-w-sm text-center">
                <h2 className="mb-2 text-lg font-semibold text-fg">Could not open this session</h2>
                <p className="mb-5 text-sm text-muted">{state.error ?? 'The session could not be loaded.'}</p>
                <Button variant="primary" icon={<Plus className="h-4 w-4" aria-hidden="true" />} onClick={() => void d.createNew()}>
                  Start a new session
                </Button>
              </div>
            </div>
          ) : (
            <>
              <ChatMessageList messages={messages} sending={state.pending.sending} />
              {statusLine && (
                <div role="status" className="border-t border-line bg-page px-4 py-2 text-sm text-muted">
                  {statusLine}
                </div>
              )}
              {session && active && (
                <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line px-4 py-1.5">
                  {confirmingClose ? (
                    <>
                      <span className="text-sm text-muted">End this session without a process to map?</span>
                      <Button size="sm" onClick={() => setConfirmingClose(false)} disabled={state.pending.closing}>
                        Keep going
                      </Button>
                      <Button
                        size="sm"
                        variant="primary"
                        disabled={state.pending.closing}
                        onClick={() => {
                          void d.closeSession().then(() => setConfirmingClose(false))
                        }}
                      >
                        {state.pending.closing ? 'Ending…' : 'Yes, end it'}
                      </Button>
                    </>
                  ) : (
                    <Button size="sm" variant="tertiary" onClick={() => setConfirmingClose(true)} disabled={state.pending.sending}>
                      No process to map — end session
                    </Button>
                  )}
                </div>
              )}
              <ChatInput value={composer} onChange={setComposer} onSend={send} disabled={composerDisabled} />
            </>
          )}
        </section>

        {session && !state.initFailed && (
          <ProcessProfilePanel
            session={session}
            sections={sections}
            onToggleSection={(id) => setSections((m) => toggleSection(m, id))}
            activeStep={shownStep}
            onSelectStep={setManualStep}
            pending={state.pending}
            locked={state.locked}
            onConfirm={(target) => void d.confirm(target)}
            onPickCluster={d.openPicker}
            onFinish={() => void d.finish()}
          />
        )}
      </main>

      {state.clusterPickerOpen && session && (
        <ClusterPicker
          currentCode={session.profile.process.cluster.code}
          saving={state.pending.settingCluster}
          error={state.clusterError}
          onSelect={(code) => void d.setCluster(code)}
          onClose={d.closePicker}
        />
      )}

      {state.sessionsModalMode && !introOpen && (
        <DiscoverySessionsModal
          mode={state.sessionsModalMode}
          sessions={state.pastSessions}
          onOpen={openFromList}
          onStartNew={() => {
            d.hidePastSessions()
            void d.createNew()
          }}
          onClose={d.hidePastSessions}
        />
      )}

      {introOpen && <DiscoveryIntroModal onDismiss={dismissIntro} />}
    </div>
  )
}
