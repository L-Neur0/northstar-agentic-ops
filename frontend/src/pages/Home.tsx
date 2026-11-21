/**
 * My processes: the expert's home page (spec 23 §3.3; AC-23.2, AC-23.3, AC-23.7–23.13).
 * Why: the home page. Without accounts, the visitor key scopes the data, so
 * this page lists the sessions and ideas saved with this browser, offers the private resume link
 * for another device, and lets the expert delete their data (F-21.1–2, F-23.4).
 * Rules: lists come from React Query (`['sessions']`, `['ideas']`), each with loading, error with
 * Retry, and empty state; a failed load never shows an empty list. Status is text with a pill as a
 * second cue; destructive actions ask first. The visitor key is shown only in the resume link box.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57).
 */
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, Link2, Plus, Trash2 } from 'lucide-react'
import { AppHeader } from '../components/layout/AppHeader'
import { Alert } from '../components/ui/Alert'
import { Button } from '../components/ui/Button'
import { Modal } from '../components/ui/Modal'
import { Pill, type PillTone } from '../components/ui/Pill'
import { Spinner } from '../components/ui/Spinner'
import { IdeasList } from '../components/process-discovery/IdeasList'
import { useApi } from '../services/apiContext'
import { PRODUCT_TAGLINE } from '../config/product'
import { DISPLAY_NAME_MAX, displayNameForCreate, readDisplayName, writeDisplayName } from '../access/displayName'
import { isStorageAvailable, peekAccessNotice, resumeLink, takeAccessNotice } from '../access/visitorKey'
import { completenessPct, formatRelativeTime, sessionStatusText } from '../utils/discoveryFormat'
import { errorText } from '../utils/discoveryErrors'
import type { Idea, SessionSummary } from '../types/process-discovery'

const STORAGE_NOTICE = 'Your browser does not keep data for this site. Use the resume link below to come back to your processes.'

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

function statusTone(s: SessionSummary): PillTone {
  if (s.status === 'finished') return 'success'
  if (s.status === 'no_candidate') return 'neutral'
  return 'info'
}

function ListState({ loading, error, onRetry, what }: { loading: boolean; error: unknown; onRetry: () => void; what: string }) {
  if (loading) {
    return (
      <p role="status" className="flex items-center gap-2 py-3 text-sm text-muted">
        <Spinner size="sm" /> Loading your {what}…
      </p>
    )
  }
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3 rounded border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger">
      <span>
        Could not load your {what}. {errorText(error)}
      </span>
      <Button size="sm" onClick={onRetry}>
        Retry
      </Button>
    </div>
  )
}

function ConfirmDialog({
  title,
  body,
  confirmLabel,
  onConfirm,
  onCancel,
  busy,
}: {
  title: string
  body: string
  confirmLabel: string
  onConfirm: () => void
  onCancel: () => void
  busy: boolean
}) {
  const cancel = useRef<HTMLButtonElement>(null)
  return (
    <Modal
      role="alertdialog"
      size="sm"
      title={title}
      description={body}
      onClose={onCancel}
      dismissible={!busy}
      initialFocusRef={cancel}
      footer={
        <>
          <Button ref={cancel} onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button variant="danger" onClick={onConfirm} loading={busy}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      {null}
    </Modal>
  )
}

export function Home() {
  const api = useApi()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [accessNotice, setAccessNotice] = useState(() => peekAccessNotice())
  const [storageOk] = useState(() => isStorageAvailable())
  const [deletedNotice, setDeletedNotice] = useState<string | null>(null)
  const [firstName, setFirstName] = useState(() => readDisplayName())
  const [showLink, setShowLink] = useState(false)
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'manual'>('idle')
  const [toDelete, setToDelete] = useState<SessionSummary | null>(null)
  const [ideaToDelete, setIdeaToDelete] = useState<Idea | null>(null)
  const [wipeOpen, setWipeOpen] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const linkInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    takeAccessNotice()
  }, [])

  const sessions = useQuery({ queryKey: ['sessions'], queryFn: () => api.listSessions() })
  const ideas = useQuery({ queryKey: ['ideas'], queryFn: () => api.listIdeas() })
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['sessions'] })
    void queryClient.invalidateQueries({ queryKey: ['ideas'] })
  }
  const fail = (e: unknown) => setActionError(errorText(e))

  const create = useMutation({
    mutationFn: () => api.createSession({ displayName: displayNameForCreate() }),
    onSuccess: (s) => navigate(`/process-discovery/${s.id}`),
    onError: fail,
  })
  const removeSession = useMutation({
    mutationFn: (id: string) => api.deleteSession(id),
    onSuccess: () => {
      setToDelete(null)
      void queryClient.invalidateQueries({ queryKey: ['sessions'] })
    },
    onError: (e) => {
      setToDelete(null)
      fail(e)
    },
  })
  const startIdea = useMutation({
    mutationFn: (id: string) => api.startIdea(id),
    onSuccess: (s) => {
      refresh()
      navigate(`/process-discovery/${s.id}`)
    },
    onError: fail,
  })
  const removeIdea = useMutation({
    mutationFn: (id: string) => api.deleteIdea(id),
    onSuccess: () => {
      setIdeaToDelete(null)
      void queryClient.invalidateQueries({ queryKey: ['ideas'] })
    },
    onError: (e) => {
      setIdeaToDelete(null)
      fail(e)
    },
  })
  const wipe = useMutation({
    mutationFn: () => api.deleteMyData(),
    onSuccess: (counts) => {
      setWipeOpen(false)
      setDeletedNotice(`Deleted ${plural(counts.sessions, 'session', 'sessions')} and ${plural(counts.ideas, 'idea', 'ideas')}.`)
      refresh()
    },
    onError: (e) => {
      setWipeOpen(false)
      fail(e)
    },
  })

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(resumeLink())
      setCopyState('copied')
    } catch {
      linkInput.current?.select()
      setCopyState('manual')
    }
  }

  const startButton = (
    <Button variant="primary" icon={<Plus className="h-4 w-4" aria-hidden="true" />} loading={create.isPending} onClick={() => create.mutate()}>
      Start a new interview
    </Button>
  )

  return (
    <div className="flex min-h-screen flex-col bg-page">
      <AppHeader actions={startButton} />
      {accessNotice && (
        <Alert tone="info" onClose={() => setAccessNotice(null)}>
          {accessNotice}
        </Alert>
      )}
      {!storageOk && <Alert tone="info">{STORAGE_NOTICE}</Alert>}
      {deletedNotice && (
        <Alert tone="info" onClose={() => setDeletedNotice(null)}>
          {deletedNotice}
        </Alert>
      )}
      {actionError && (
        <Alert tone="error" onClose={() => setActionError(null)}>
          {actionError}
        </Alert>
      )}

      <main className="mx-auto flex w-full max-w-5xl flex-col gap-8 px-4 py-6">
        <p className="text-sm text-muted">{PRODUCT_TAGLINE}</p>
        <section>
          <h2 className="mb-3 text-xl font-semibold text-fg">My processes</h2>
          <div className="flex flex-wrap items-center gap-3">
            <label htmlFor="first-name" className="text-sm font-medium text-fg">
              First name (optional)
            </label>
            <input
              id="first-name"
              value={firstName}
              maxLength={DISPLAY_NAME_MAX}
              onChange={(e) => {
                setFirstName(e.target.value)
                writeDisplayName(e.target.value)
              }}
              aria-describedby="first-name-hint"
              className="w-48 rounded-md border border-line-strong bg-surface px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
            />
            <span id="first-name-hint" className="text-xs text-subtle">
              Used only to greet you.
            </span>
          </div>
        </section>

        <section aria-labelledby="sessions-heading">
          <h3 id="sessions-heading" className="mb-2 text-base font-semibold text-fg">
            Sessions
          </h3>
          {sessions.data ? (
            sessions.data.sessions.length === 0 ? (
              <div className="rounded-lg border border-dashed border-line-strong bg-surface px-4 py-6 text-center">
                <p className="mb-3 text-sm text-muted">No sessions yet. Map your first process in about 15 minutes.</p>
                <Button variant="primary" icon={<Plus className="h-4 w-4" aria-hidden="true" />} onClick={() => create.mutate()}>
                  Start a new interview
                </Button>
              </div>
            ) : (
              <div className="overflow-x-auto rounded-lg border border-line bg-surface">
                <table aria-label="Sessions" className="w-full text-left text-sm">
                  <thead className="bg-page text-xs uppercase tracking-wide text-subtle">
                    <tr>
                      <th scope="col" className="px-4 py-2 font-medium">Process</th>
                      <th scope="col" className="px-4 py-2 font-medium">Status</th>
                      <th scope="col" className="px-4 py-2 font-medium">Complete</th>
                      <th scope="col" className="px-4 py-2 font-medium">Last activity</th>
                      <th scope="col" className="px-4 py-2 font-medium">
                        <span className="sr-only">Actions</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {sessions.data.sessions.map((s) => {
                      const name = s.processName || 'Not named yet'
                      return (
                        <tr key={s.id}>
                          <th scope="row" className={`px-4 py-2.5 font-medium ${s.processName ? 'text-fg' : 'italic text-subtle'}`}>
                            {name}
                          </th>
                          <td className="px-4 py-2.5">
                            <Pill tone={statusTone(s)}>{sessionStatusText(s)}</Pill>
                          </td>
                          <td className="px-4 py-2.5 text-fg">{completenessPct(s.score)} %</td>
                          <td className="px-4 py-2.5 text-muted">{formatRelativeTime(s.updatedAt)}</td>
                          <td className="px-4 py-2.5">
                            <div className="flex justify-end gap-2">
                              {s.status === 'active' && (
                                <Link to={`/process-discovery/${s.id}`} className="rounded-md bg-primary px-2.5 py-1 text-xs font-medium text-primary-contrast hover:bg-primary-hover">
                                  Continue
                                </Link>
                              )}
                              {s.status === 'finished' && (
                                <Link to={`/report/${s.id}`} className="rounded-md border border-line-strong px-2.5 py-1 text-xs font-medium text-fg hover:bg-surface-muted">
                                  Open report
                                </Link>
                              )}
                              <Button
                                size="sm"
                                variant="tertiary"
                                aria-label={`Delete ${name}`}
                                icon={<Trash2 className="h-3.5 w-3.5" aria-hidden="true" />}
                                onClick={() => setToDelete(s)}
                              >
                                Delete
                              </Button>
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )
          ) : (
            <ListState loading={sessions.isPending} error={sessions.error} onRetry={() => void sessions.refetch()} what="sessions" />
          )}
        </section>

        <section aria-labelledby="ideas-heading">
          <h3 id="ideas-heading" className="mb-2 text-base font-semibold text-fg">
            Ideas <span className="text-sm font-normal text-subtle">(processes you mentioned and can map later)</span>
          </h3>
          {ideas.data ? (
            <IdeasList
              ideas={ideas.data.ideas}
              busyId={startIdea.isPending ? (startIdea.variables ?? null) : null}
              onMap={(id) => startIdea.mutate(id)}
              onDelete={setIdeaToDelete}
            />
          ) : (
            <ListState loading={ideas.isPending} error={ideas.error} onRetry={() => void ideas.refetch()} what="ideas" />
          )}
        </section>

        <section aria-labelledby="resume-heading" className="rounded-lg border border-line bg-surface p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 id="resume-heading" className="text-base font-semibold text-fg">
              Continue on another device
            </h3>
            {!showLink && (
              <Button icon={<Link2 className="h-4 w-4" aria-hidden="true" />} onClick={() => setShowLink(true)}>
                Show resume link
              </Button>
            )}
          </div>
          {showLink && (
            <div className="mt-3">
              <div className="flex flex-wrap gap-2">
                <input
                  ref={linkInput}
                  readOnly
                  aria-label="Resume link"
                  value={resumeLink()}
                  onFocus={(e) => e.target.select()}
                  className="min-w-0 flex-1 rounded-md border border-line-strong bg-page px-2 py-1 font-mono text-xs text-fg"
                />
                <Button icon={<Copy className="h-4 w-4" aria-hidden="true" />} onClick={() => void copy()}>
                  {copyState === 'copied' ? 'Copied' : 'Copy'}
                </Button>
              </div>
              {copyState === 'manual' && <p className="mt-1 text-xs text-muted">Press Ctrl+C to copy.</p>}
              <p className="mt-2 text-sm text-warning">Anyone with this link sees your processes. Keep it private.</p>
            </div>
          )}
        </section>

        <section aria-labelledby="data-heading" className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-line bg-surface p-4">
          <h3 id="data-heading" className="text-base font-semibold text-fg">
            Your data
          </h3>
          <Button variant="danger" icon={<Trash2 className="h-4 w-4" aria-hidden="true" />} onClick={() => setWipeOpen(true)}>
            Delete all my data
          </Button>
        </section>
      </main>

      {toDelete && (
        <ConfirmDialog
          title="Delete this session?"
          body="This cannot be undone."
          confirmLabel="Delete"
          busy={removeSession.isPending}
          onCancel={() => setToDelete(null)}
          onConfirm={() => removeSession.mutate(toDelete.id)}
        />
      )}
      {ideaToDelete && (
        <ConfirmDialog
          title="Delete this idea?"
          body={`"${ideaToDelete.name}" will be removed from your ideas. This cannot be undone.`}
          confirmLabel="Delete"
          busy={removeIdea.isPending}
          onCancel={() => setIdeaToDelete(null)}
          onConfirm={() => removeIdea.mutate(ideaToDelete.id)}
        />
      )}
      {wipeOpen && (
        <ConfirmDialog
          title="Delete all your data?"
          body="This deletes every session and idea saved with this browser. It cannot be undone."
          confirmLabel="Delete everything"
          busy={wipe.isPending}
          onCancel={() => setWipeOpen(false)}
          onConfirm={() => wipe.mutate()}
        />
      )}
    </div>
  )
}
