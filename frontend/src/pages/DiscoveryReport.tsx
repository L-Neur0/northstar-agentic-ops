/**
 * The discovery report page, route `/report/:sessionId` (spec 23 §11.10–§11.14; AC-23.82–23.86,
 * AC-23.97, AC-23.99, AC-23.100).
 * Why: after *Finish* the expert reads the cover and the eleven parts of spec 20, sees the map,
 * and downloads the PDF to share; this page shows exactly the server's report model.
 * Rules: one `GET …/report` per open (React Query `['report', id]`, no retry, no polling); a part
 * that is missing or breaks shows its heading and a plain sentence while the others render; a
 * report that is not ready (404 or 409 `report_not_ready`) reads the same as "not yours"; the PDF
 * is fetched with the visitor key and saved through a revoked object URL; print hides the header,
 * contents and buttons. Must not: format any value, show a euro figure, a transcript or a
 * document's text, or call the model.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57, AC-23.102).
 */
import { useEffect, useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Download, RotateCcw } from 'lucide-react'
import { AppHeader } from '../components/layout/AppHeader'
import { Button } from '../components/ui/Button'
import { Spinner } from '../components/ui/Spinner'
import { ReportNoteBox } from '../components/report/ReportNote'
import { ReportPartBoundary } from '../components/report/ReportPartBoundary'
import type { MapRenderer } from '../components/report/ProcessMap'
import {
  AtAGlance,
  GapsAndSources,
  HoursTables,
  MapAndSteps,
  OpportunityList,
  ReadinessTable,
  RecommendedRoute,
  ReportCover,
  ReportFields,
  StepAssessmentTable,
  SuggestedPath,
} from '../components/report/ReportParts'
import { useApi } from '../services/apiContext'
import { ApiError } from '../services/api'
import { loadReport } from '../services/wireGuards'
import { errorText } from '../utils/discoveryErrors'
import { saveBlob } from '../utils/downloadFile'
import { PART_FALLBACK_TITLES, PART_KEYS, type LoadedReport, type PartBase, type PartKey } from '../types/report'

const SLOW_AFTER_MS = 10_000

/** `atAGlance` → `at_a_glance`, the anchor key of spec 23 §11.10.5. */
const anchorOf = (key: PartKey) => `part-${key.replace(/[A-Z]/g, (c) => `_${c.toLowerCase()}`)}`

function PartSection({ partKey, index, part, children }: { partKey: PartKey; index: number; part: PartBase | null; children?: ReactNode }) {
  const id = anchorOf(partKey)
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="mt-8 scroll-mt-4">
      <h2 id={`${id}-title`} className="mb-2 border-b border-line pb-1 text-lg font-semibold text-fg break-after-avoid">
        {part ? `${part.number}. ${part.title}` : `${index + 1}. ${PART_FALLBACK_TITLES[partKey]}`}
      </h2>
      {part?.note && <ReportNoteBox kind={part.note.kind} text={part.note.text} />}
      {children}
    </section>
  )
}

function renderPart(key: PartKey, report: LoadedReport, mapRenderer?: MapRenderer): ReactNode {
  switch (key) {
    case 'atAGlance':
      return report.atAGlance && <AtAGlance part={report.atAGlance} />
    case 'process':
      return report.process && <ReportFields part={report.process} />
    case 'measures':
      return report.measures && <ReportFields part={report.measures} />
    case 'map':
      return report.map && <MapAndSteps part={report.map} render={mapRenderer} />
    case 'steps':
      return report.steps && <StepAssessmentTable part={report.steps} />
    case 'route':
      return report.route && <RecommendedRoute part={report.route} />
    case 'assessment':
      return report.assessment && <OpportunityList part={report.assessment} />
    case 'potential':
      return report.potential && <HoursTables part={report.potential} />
    case 'readiness':
      return report.readiness && <ReadinessTable part={report.readiness} />
    case 'path':
      return report.path && <SuggestedPath part={report.path} />
    case 'gaps':
      return report.gaps && <GapsAndSources part={report.gaps} />
  }
}

function titleOf(key: PartKey, index: number, report: LoadedReport): string {
  const part = report[key] as PartBase | null
  return part ? `${part.number}. ${part.title}` : `${index + 1}. ${PART_FALLBACK_TITLES[key]}`
}

function ContentsLinks({ report }: { report: LoadedReport }) {
  return (
    <ol className="flex flex-col gap-1 text-sm">
      {PART_KEYS.map((key, i) => (
        <li key={key}>
          <a href={`#${anchorOf(key)}`} className="text-link hover:underline">
            {titleOf(key, i, report)}
          </a>
        </li>
      ))}
    </ol>
  )
}

/** The report body: cover, contents and the eleven parts (exported for the part tests). */
export function ReportView({ report, mapRenderer }: { report: LoadedReport; mapRenderer?: MapRenderer }) {
  return (
    <div className="mx-auto flex w-full max-w-[1280px] gap-8 px-4 py-6">
      <aside className="hidden w-56 shrink-0 lg:block print:hidden">
        <nav aria-label="Report contents" className="sticky top-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Contents</p>
          <ContentsLinks report={report} />
        </nav>
      </aside>
      <article className="min-w-0 max-w-[960px] flex-1">
        <details className="mb-4 rounded-md border border-line p-2 lg:hidden print:hidden">
          <summary className="cursor-pointer text-sm font-medium text-fg">Contents</summary>
          <div className="mt-2">
            <ContentsLinks report={report} />
          </div>
        </details>
        {report.cover ? (
          <ReportCover cover={report.cover} />
        ) : (
          <div className="mb-6">
            <h2 className="text-2xl font-bold text-fg">Discovery report</h2>
            <ReportNoteBox kind="failed" text="This part could not be generated." />
          </div>
        )}
        {PART_KEYS.map((key, i) => {
          const part = report[key] as PartBase | null
          if (!part) {
            return (
              <PartSection key={key} partKey={key} index={i} part={null}>
                <ReportNoteBox kind="failed" text="This part could not be generated." />
              </PartSection>
            )
          }
          return (
            <ReportPartBoundary
              key={key}
              fallback={
                <PartSection partKey={key} index={i} part={null}>
                  <ReportNoteBox kind="error" text="This part could not be shown." />
                </PartSection>
              }
            >
              <PartSection partKey={key} index={i} part={part}>
                {renderPart(key, report, mapRenderer)}
              </PartSection>
            </ReportPartBoundary>
          )
        })}
      </article>
    </div>
  )
}

function useSlow(active: boolean, ms: number): boolean {
  const [slow, setSlow] = useState(false)
  useEffect(() => {
    if (!active) return
    const t = setTimeout(() => setSlow(true), ms)
    return () => {
      clearTimeout(t)
      setSlow(false)
    }
  }, [active, ms])
  return slow
}

function PdfButton({ sessionId, compact = false }: { sessionId: string; compact?: boolean }) {
  const api = useApi()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const download = async () => {
    setBusy(true)
    setError(null)
    try {
      const { blob, filename } = await api.getReportPdf(sessionId)
      saveBlob(blob, filename)
    } catch (e) {
      setError(e instanceof ApiError && e.status === 404 ? 'This report is not available.' : errorText(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <span className="inline-flex items-center gap-2 print:hidden">
      <Button
        variant="primary"
        aria-label={compact ? 'Download PDF' : undefined}
        icon={<Download className="h-4 w-4" aria-hidden="true" />}
        loading={busy}
        onClick={() => void download()}
      >
        {busy ? (
          'Preparing PDF…'
        ) : compact ? (
          <span className="hidden sm:inline">Download PDF</span>
        ) : (
          'Download PDF'
        )}
      </Button>
      {error && (
        <span role="alert" className="text-sm text-danger">
          {error}
        </span>
      )}
    </span>
  )
}

const notReady = (e: unknown) => e instanceof ApiError && (e.status === 404 || e.code === 'report_not_ready')

export function DiscoveryReport({ mapRenderer }: { mapRenderer?: MapRenderer }) {
  const { sessionId = '' } = useParams<{ sessionId: string }>()
  const api = useApi()
  const report = useQuery({
    queryKey: ['report', sessionId],
    queryFn: async () => loadReport(await api.getReport(sessionId)),
    retry: false,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  })
  const slow = useSlow(report.isPending, SLOW_AFTER_MS)

  let body: ReactNode
  if (report.isPending) {
    body = (
      <div role="status" className="flex items-center justify-center gap-2 p-10 text-sm text-muted">
        <Spinner /> {slow ? 'Still building your report. This can take up to a minute.' : 'Loading your report…'}
      </div>
    )
  } else if (report.isError) {
    body = notReady(report.error) ? (
      <div className="mx-auto max-w-lg p-10 text-center">
        <p className="mb-4 text-fg">This report is not available. A report is ready once the interview is finished.</p>
        <div className="flex flex-wrap justify-center gap-2">
          <Link to={`/process-discovery/${sessionId}`} className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-contrast hover:bg-primary-hover">
            Continue the interview
          </Link>
          <Link to="/" className="rounded-md border border-line-strong px-3 py-1.5 text-sm font-medium text-fg hover:bg-surface-muted">
            Back to My processes
          </Link>
        </div>
      </div>
    ) : (
      <div className="mx-auto max-w-lg p-10 text-center">
        <p role="alert" className="mb-4 text-fg">
          {errorText(report.error)}
        </p>
        <Button icon={<RotateCcw className="h-4 w-4" aria-hidden="true" />} onClick={() => void report.refetch()}>
          Retry
        </Button>
      </div>
    )
  } else {
    body = (
      <>
        <ReportView report={report.data} mapRenderer={mapRenderer} />
        <div className="mx-auto mb-10 flex max-w-[960px] justify-end px-4">
          <PdfButton sessionId={sessionId} />
        </div>
      </>
    )
  }

  return (
    <div className="flex min-h-screen flex-col bg-page print:bg-surface">
      <div data-testid="report-header" className="print:hidden">
        <AppHeader
          actions={
            <>
              {report.isSuccess && <PdfButton sessionId={sessionId} compact />}
              <Link
                to="/"
                aria-label="Back to My processes"
                className="inline-flex items-center gap-1.5 rounded-md border border-line-strong bg-surface px-3 py-1.5 text-sm font-medium text-fg hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
              >
                <ArrowLeft className="h-4 w-4" aria-hidden="true" />
                <span className="hidden sm:inline">Back to My processes</span>
              </Link>
            </>
          }
        />
      </div>
      <main className="flex-1">{body}</main>
    </div>
  )
}
