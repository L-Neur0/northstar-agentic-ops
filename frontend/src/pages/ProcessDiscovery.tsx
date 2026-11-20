/**
 * The interview page: chat on the left, "Your process" on the right, phase meter on top
 * (spec 23 §3.4–3.9, §11.1–§11.9; AC-23.14–23.16, 23.21–23.27, 23.32, 23.40, 23.41, 23.44, 23.45,
 * 23.49, 23.61–23.79, 23.103–23.105).
 * Why: the Process Discovery page, styled with Tailwind: same header
 * actions, same layout (chat 60 %, panel up to 480 px), same honest exit, same first-visit intro
 * and welcome-back dialog; the Copilot prompt and analysis buttons are replaced by *Finish*.
 * Rules: server-derived state lives in `useDiscoveryState`; presentation state (open sections,
 * chosen step tab, two-press exit, intro, composer text) stays here and survives every response.
 * The two endings are told apart by `status`; "report ready" is never shown for `no_candidate`.
 * Part 2: one hidden file input serves the "+" button left of the message box (the main entry),
 * the hint card and the Documents panel; a file dropped on the chat or the panel uploads the same
 * way; the document limits come from `GET /api/config` (React Query `['config']`, loaded once).
 * Must not compute completeness, decide a phase, count proposals or read a file's content.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57).
 */
import { useRef, useState, type DragEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, History, Info, Plus } from 'lucide-react'
import { AppHeader } from '../components/layout/AppHeader'
import { Alert } from '../components/ui/Alert'
import { Button } from '../components/ui/Button'
import { Spinner } from '../components/ui/Spinner'
import { ChatInput } from '../components/chat/ChatInput'
import { ChatMessageList } from '../components/chat/ChatMessageList'
import { AttachButton } from '../components/chat/AttachButton'
import { DocumentHint } from '../components/process-discovery/DocumentHint'
import type { ProposalControls } from '../components/process-discovery/ProposalActions'
import { isWriting } from '../hooks/discoveryReducer'
import { useApi } from '../services/apiContext'
import { acceptOf, documentSentence } from '../utils/documentLimits'
import { DiscoveryPhaseMeter } from '../components/process-discovery/DiscoveryPhaseMeter'
import { ProcessProfilePanel } from '../components/process-discovery/ProcessProfilePanel'
import { ClusterPicker } from '../components/process-discovery/ClusterPicker'
import { DiscoverySessionsModal } from '../components/process-discovery/DiscoverySessionsModal'
import { DiscoveryIntroModal } from '../components/process-discovery/DiscoveryIntroModal'
import { hasSeenIntro, markIntroSeen } from '../components/process-discovery/introStorage'
import { applyPhase, defaultSections, toggleSection, type SectionStateMap } from '../components/process-discovery/sectionState'
import { useDiscoveryState } from '../hooks/useDiscoveryState'
import { activeStepIndex } from '../utils/substepProgress'
import { IMAGE_KINDS, type Phase, type SessionSummary } from '../types/process-discovery'

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
  const api = useApi()
  const config = useQuery({ queryKey: ['config'], queryFn: () => api.getConfig(), staleTime: Infinity })
  const limits = config.data?.documents ?? null
  const fileInput = useRef<HTMLInputElement>(null)
  const [openQuotes, setOpenQuotes] = useState<ReadonlySet<string>>(new Set())

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
  const writing = isWriting(state.pending)
  const composerDisabled = state.loading || state.pending.sending || state.locked || session?.status !== 'active' || writing
  const documents = session?.documents ?? []
  const atLimit = limits !== null && documents.length >= limits.maxFiles
  const turnOrConfirm = state.pending.sending || state.pending.confirming !== null || state.pending.finishing
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

  /** Opens the file picker, or says why not when the limit is reached (spec 23 §11.3.6). */
  const openPicker = () => {
    if (atLimit) d.showDocumentError(documentSentence('document_limit', limits))
    else fileInput.current?.click()
  }
  const upload = (file: File) => void d.uploadDocument(file, limits)
  const canDrop = active && !writing && !turnOrConfirm

  const onChatDrop = (e: DragEvent) => {
    if (!Array.from(e.dataTransfer?.types ?? []).includes('Files')) return
    e.preventDefault()
    const file = e.dataTransfer.files?.[0]
    if (file && canDrop) upload(file)
  }

  let attachReason: string | null = null
  if (!active) attachReason = 'This session is closed.'
  else if (state.pending.sending) attachReason = 'Wait for the reply before adding a document.'
  else if (writing || turnOrConfirm) attachReason = 'Wait for the current change to finish.'
  else if (atLimit) attachReason = documentSentence('document_limit', limits)

  const proposals: ProposalControls = {
    canAct: active,
    disabled: writing || turnOrConfirm,
    pending: state.pending.proposals,
    openQuotes,
    onToggleQuote: (key) =>
      setOpenQuotes((prev) => {
        const next = new Set(prev)
        if (next.has(key)) next.delete(key)
        else next.add(key)
        return next
      }),
    onConfirm: (keys) => void d.confirmProposals(keys),
    onReject: (key, label) => void d.rejectProposals([key], label),
    imageDocuments: new Set((session?.documents ?? []).filter((doc) => IMAGE_KINDS.includes(doc.kind)).map((doc) => doc.name)),
  }
  const showHint = active && documents.length === 0 && (session?.phase === 'context' || session?.phase === 'find')

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
  } else if (state.proposalNotice) {
    statusLine = state.proposalNotice
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
        <section
          aria-label="Discovery conversation"
          className="flex h-[85vh] min-w-0 flex-col lg:h-auto lg:min-h-0 lg:flex-[3]"
          onDragOver={(e) => {
            if (canDrop && Array.from(e.dataTransfer?.types ?? []).includes('Files')) e.preventDefault()
          }}
          onDrop={onChatDrop}
        >
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
              <ChatMessageList
                messages={messages}
                sending={state.pending.sending}
                afterFirstAgent={showHint ? <DocumentHint onAdd={openPicker} disabled={writing || turnOrConfirm} /> : null}
              />
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
                    <Button size="sm" variant="tertiary" onClick={() => setConfirmingClose(true)} disabled={state.pending.sending || writing}>
                      No process to map — end session
                    </Button>
                  )}
                </div>
              )}
              <ChatInput
                value={composer}
                onChange={setComposer}
                onSend={send}
                disabled={composerDisabled}
                leading={
                  session ? (
                    <AttachButton onClick={openPicker} uploading={state.pending.uploading !== null} disabledReason={attachReason} />
                  ) : null
                }
              />
              <input
                ref={fileInput}
                type="file"
                className="hidden"
                data-testid="document-input"
                aria-label="Choose a document"
                tabIndex={-1}
                accept={limits ? acceptOf(limits) : undefined}
                onChange={(e) => {
                  const file = e.target.files?.[0]
                  e.target.value = ''
                  if (file) upload(file)
                }}
              />
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
            proposals={proposals}
            documentPanel={{
              editable: active,
              busy: writing || turnOrConfirm,
              limits,
              uploading: state.pending.uploading,
              removingId: state.pending.removingDocument,
              notice: state.documentNotice,
              error: state.documentError,
              onOpenPicker: openPicker,
              onFile: upload,
              onRemove: (docId) => void d.removeDocument(docId),
              onDismissNotice: d.clearDocumentNotice,
              onDismissError: d.clearDocumentError,
            }}
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
