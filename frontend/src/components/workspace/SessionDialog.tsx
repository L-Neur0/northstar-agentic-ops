/**
 * The read-only session popup of the workspace (spec 23 §19.4, §19.5, §19.7; AC-23.122–23.137).
 * Why: from the list, the specialist opens one session and sees its summary, its steps (now or
 * as first told), the documents, the AI assessment and the map, reads the conversation, downloads
 * the report PDF, or deletes the session.
 * Rules: one view call per open and one conversation call when that tab is first opened (both
 * dropped when the popup closes); the report parts reuse the part 2 components inside error
 * boundaries; the PDF is fetched with the bearer token; delete asks in a stacked `alertdialog`,
 * sends the loaded etag, and on 409 reloads the view; any 401 / 403 hands the error to the page
 * (`onSessionEnded`). With `canDelete={false}` (open demo workspace, spec 23 §19.7 rule 8,
 * AC-23.144, amended 2026-11-20) the Delete button is not rendered. Must not: edit anything — delete is the only write (AC-23.138).
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.141).
 */
import { useId, useRef, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Download, RotateCcw, Trash2 } from 'lucide-react'
import { Modal } from '../ui/Modal'
import { Tabs } from '../ui/Tabs'
import { Button } from '../ui/Button'
import { Spinner } from '../ui/Spinner'
import { ReportNoteBox } from '../report/ReportNote'
import { ReportPartBoundary } from '../report/ReportPartBoundary'
import { OpportunityList, RecommendedRoute, StepAssessmentTable } from '../report/ReportParts'
import { ProcessMap, type MapRenderer } from '../report/ProcessMap'
import { SummaryCards } from './SummaryCards'
import { StepGrid } from './StepGrid'
import { ConversationView } from './ConversationView'
import { useApi } from '../../services/apiContext'
import { ApiError } from '../../services/api'
import { loadReport } from '../../services/wireGuards'
import { saveBlob } from '../../utils/downloadFile'
import { isSessionEnded, watchSession, workspaceErrorText, WORKSPACE_TEXT } from '../../utils/discoveryErrors'
import { formatRelativeTime } from '../../utils/discoveryFormat'
import { formatDate, kindWord, outcomeWord } from '../../utils/workspaceFormat'
import { PART_FALLBACK_TITLES, type LoadedReport, type PartBase, type PartKey } from '../../types/report'
import type { DocumentMeta, ReviewRow } from '../../types/workspace'

const ONCE = { retry: false, staleTime: Infinity, gcTime: 0, refetchOnWindowFocus: false } as const

/** One report block: an `<h3>` heading, the part's note, the content, inside an error boundary. */
function ReportBlock({ partKey, part, children }: { partKey: PartKey; part: PartBase | null; children: ReactNode }) {
  const id = useId()
  const title = part?.title ?? PART_FALLBACK_TITLES[partKey]
  const heading = (
    <h3 id={id} className="mb-2 border-b border-line pb-1 text-base font-semibold text-fg">
      {title}
    </h3>
  )
  return (
    <ReportPartBoundary
      fallback={
        <section aria-labelledby={id} className="mt-6">
          {heading}
          <ReportNoteBox kind="error" text="This part could not be shown." />
        </section>
      }
    >
      <section aria-labelledby={id} className="mt-6">
        {heading}
        {!part ? (
          <ReportNoteBox kind="failed" text="This part could not be generated." />
        ) : (
          <>
            {part.note && <ReportNoteBox kind={part.note.kind} text={part.note.text} />}
            {children}
          </>
        )}
      </section>
    </ReportPartBoundary>
  )
}

function ReportBlocks({ report, mapRenderer }: { report: LoadedReport; mapRenderer?: MapRenderer }) {
  return (
    <>
      <ReportBlock partKey="steps" part={report.steps}>
        {report.steps && <StepAssessmentTable part={report.steps} />}
      </ReportBlock>
      <ReportBlock partKey="route" part={report.route}>
        {report.route && <RecommendedRoute part={report.route} headingLevel={3} />}
      </ReportBlock>
      <ReportBlock partKey="assessment" part={report.assessment}>
        {report.assessment && <OpportunityList part={report.assessment} headingLevel={3} />}
      </ReportBlock>
      <ReportBlock partKey="map" part={report.map ? { ...report.map, title: 'Process map' } : null}>
        {report.map && <ProcessMap diagram={report.map.diagram} caption={report.map.caption} render={mapRenderer} />}
      </ReportBlock>
    </>
  )
}

function Documents({ documents }: { documents: DocumentMeta[] }) {
  if (documents.length === 0) return null
  return (
    <section aria-labelledby="ws-documents" className="mt-6">
      <h3 id="ws-documents" className="mb-1 text-base font-semibold text-fg">
        Documents
      </h3>
      <ul className="text-sm text-fg">
        {documents.map((d, i) => (
          <li key={i}>
            {d.name} · {kindWord(d.kind)} · {formatDate(d.uploadedAt)} · {outcomeWord(d.outcome)}
          </li>
        ))}
      </ul>
    </section>
  )
}

export function SessionDialog({
  row,
  onClose,
  onDeleted,
  onSessionEnded,
  mapRenderer,
  canDelete = true,
}: {
  row: ReviewRow
  /** `refresh`: the session was found gone, so the list should reload. */
  onClose: (refresh: boolean) => void
  /** Delete finished (or found the session already deleted): the page's status sentence. */
  onDeleted: (message: string) => void
  onSessionEnded: (error: unknown) => void
  mapRenderer?: MapRenderer
  /** False on the open demo workspace: no Delete button (spec 23 §19.7 rule 8). */
  canDelete?: boolean
}) {
  const api = useApi()
  const [tab, setTab] = useState(0)
  const [conversationOpened, setConversationOpened] = useState(false)
  const [pdfBusy, setPdfBusy] = useState(false)
  const [pdfError, setPdfError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const cancelRef = useRef<HTMLButtonElement>(null)
  const pdfReasonId = useId()

  const view = useQuery({
    queryKey: ['workspace', 'session', row.id],
    queryFn: () => watchSession(() => api.reviewSession(row.id), onSessionEnded),
    ...ONCE,
  })
  const conversation = useQuery({
    queryKey: ['workspace', 'conversation', row.id],
    queryFn: () => watchSession(() => api.reviewConversation(row.id), onSessionEnded),
    enabled: conversationOpened,
    ...ONCE,
  })

  const gone = view.error instanceof ApiError && view.error.status === 404
  const close = () => onClose(gone)
  const finished = view.data?.summary.status === 'finished'
  const report = view.data?.report ? loadReport(view.data.report) : null

  const selectTab = (i: number) => {
    setTab(i)
    if (i === 1) setConversationOpened(true)
  }

  const downloadPdf = async () => {
    setPdfBusy(true)
    setPdfError(null)
    try {
      const { blob, filename } = await api.getReviewReportPdf(row.id)
      saveBlob(blob, filename)
    } catch (e) {
      if (isSessionEnded(e)) onSessionEnded(e)
      else setPdfError(workspaceErrorText(e))
    } finally {
      setPdfBusy(false)
    }
  }

  const confirmDelete = async () => {
    if (!view.data) return
    setDeleting(true)
    try {
      await api.deleteReviewSession(row.id, view.data.etag)
      onDeleted(WORKSPACE_TEXT.deleted)
    } catch (e) {
      if (isSessionEnded(e)) onSessionEnded(e)
      else if (e instanceof ApiError && e.code === 'conflict') {
        setConfirming(false)
        setNotice(WORKSPACE_TEXT.conflict)
        await view.refetch()
      } else if (e instanceof ApiError && e.status === 404) onDeleted(WORKSPACE_TEXT.alreadyDeleted)
      else {
        setConfirming(false)
        setNotice(workspaceErrorText(e))
      }
    } finally {
      setDeleting(false)
    }
  }

  let body: ReactNode
  if (view.isPending) {
    body = (
      <p role="status" className="flex items-center gap-2 p-6 text-sm text-muted">
        <Spinner /> Loading the session…
      </p>
    )
  } else if (view.isError) {
    body = gone ? (
      <p className="p-6 text-sm text-fg">{WORKSPACE_TEXT.sessionGone}</p>
    ) : (
      <div className="flex flex-col items-start gap-2 p-4">
        <p role="alert" className="text-sm text-danger">
          {workspaceErrorText(view.error)}
        </p>
        <Button icon={<RotateCcw className="h-4 w-4" aria-hidden="true" />} onClick={() => void view.refetch()}>
          Retry
        </Button>
      </div>
    )
  } else {
    const data = view.data
    body = (
      <>
        <Tabs items={[{ id: 'session', label: 'Session' }, { id: 'conversation', label: 'Conversation' }]} selected={tab} onSelect={selectTab} label="Session views" idPrefix="ws-session" />
        <div role="tabpanel" id="ws-session-panel" aria-labelledby={`ws-session-tab-${tab}`} className="pt-4">
          {notice && (
            <p role="alert" className="mb-3 rounded-md border border-warning/40 bg-warning-soft px-3 py-2 text-sm text-warning">
              {notice}
            </p>
          )}
          {tab === 0 ? (
            <>
              <SummaryCards summary={data.summary} />
              <div className="mt-6">
                <StepGrid steps={data.steps} rawSteps={data.rawSteps} />
              </div>
              <Documents documents={data.documents} />
              {report ? (
                <ReportBlocks report={report} mapRenderer={mapRenderer} />
              ) : (
                <div className="mt-6">
                  <ReportNoteBox kind="missing" text="The assessment and the map are ready once the expert finishes the interview." />
                </div>
              )}
            </>
          ) : (
            <ConversationView
              messages={conversation.data?.messages}
              loading={conversation.isPending}
              error={conversation.error}
              onRetry={() => void conversation.refetch()}
            />
          )}
        </div>
      </>
    )
  }

  const footer = (
    <>
      {view.data && canDelete && (
        <div className="mr-auto">
          <Button variant="danger" icon={<Trash2 className="h-4 w-4" aria-hidden="true" />} disabled={deleting} onClick={() => setConfirming(true)}>
            Delete session
          </Button>
        </div>
      )}
      {view.data && (
        <span className="inline-flex flex-wrap items-center gap-2">
          {!finished && (
            <span id={pdfReasonId} className="text-xs text-muted">
              {WORKSPACE_TEXT.reportNotReady}
            </span>
          )}
          {pdfError && (
            <span role="alert" className="text-sm text-danger">
              {pdfError}
            </span>
          )}
          <Button
            icon={<Download className="h-4 w-4" aria-hidden="true" />}
            disabled={!finished}
            aria-describedby={finished ? undefined : pdfReasonId}
            loading={pdfBusy}
            onClick={() => void downloadPdf()}
          >
            {pdfBusy ? 'Preparing PDF…' : 'Download report (PDF)'}
          </Button>
        </span>
      )}
      <Button disabled={deleting} onClick={close}>
        Close
      </Button>
    </>
  )

  return (
    <>
      <Modal
        title={row.processName ?? 'Not named yet'}
        description={`Session ${row.id} · Updated ${formatRelativeTime(row.updatedAt)}`}
        onClose={close}
        dismissible={!deleting}
        size="xl"
        footer={footer}
      >
        {body}
      </Modal>
      {confirming && (
        <Modal
          role="alertdialog"
          title="Delete this session?"
          size="sm"
          onClose={() => setConfirming(false)}
          dismissible={!deleting}
          initialFocusRef={cancelRef}
          footer={
            <>
              <Button ref={cancelRef} disabled={deleting} onClick={() => setConfirming(false)}>
                Cancel
              </Button>
              <Button variant="danger" loading={deleting} onClick={() => void confirmDelete()}>
                {deleting ? 'Deleting…' : 'Delete session'}
              </Button>
            </>
          }
        >
          <p className="text-sm text-fg">
            This removes the session, its map and its report for everyone, including the expert. The expert's ideas stay. This
            cannot be undone.
          </p>
        </Modal>
      )}
    </>
  )
}
