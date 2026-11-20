/**
 * The workspace page, route `/workspace` (spec 23 §19.1–§19.3; AC-23.106, AC-23.108,
 * AC-23.113–23.117, AC-23.135, AC-23.142).
 * Why: the IT and transformation specialist logs in with the access code and a name, sees every
 * discovery session in one filtered list, and opens one read-only popup; this page holds the
 * token state, the filters, the list query and which popup is open.
 * Rules: login when there is no valid token; any 401 `workspace_code_required` or 403 on a
 * workspace call clears the token, closes the popup and shows the login with its sentence; the
 * list keeps the server's order and counts, keeps previous rows while a filter loads, and a
 * failed list is an alert with **Retry** (never an empty list or zero counts); after a delete the
 * list refetches and a dismissible status says so. No link to this page from the expert's screens.
 * Open demo workspace (`workspaceOpen` from `GET /api/config`, spec 23 §19.2 rule 10, §19.7 rule 8;
 * amended 2026-11-20): the login asks for the name only and the popup has no Delete button; a
 * config still loading or failed counts as closed for the login, and loading hides Delete.
 * Must not: edit a session, send the visitor key, or keep filters in the URL or storage.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.141).
 */
import { useCallback, useRef, useState } from 'react'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { LogOut, RefreshCw, RotateCcw } from 'lucide-react'
import { AppHeader } from '../components/layout/AppHeader'
import { Alert } from '../components/ui/Alert'
import { Button } from '../components/ui/Button'
import { Spinner } from '../components/ui/Spinner'
import { WorkspaceLogin } from '../components/workspace/WorkspaceLogin'
import { SessionFilters } from '../components/workspace/SessionFilters'
import { CountsLine, SessionTable } from '../components/workspace/SessionTable'
import { SessionDialog } from '../components/workspace/SessionDialog'
import type { MapRenderer } from '../components/report/ProcessMap'
import { useApi } from '../services/apiContext'
import { clearWorkspaceToken, readWorkspaceToken } from '../access/workspaceToken'
import { sessionEndedText, watchSession, workspaceErrorText } from '../utils/discoveryErrors'
import { NO_FILTERS } from '../utils/workspaceFormat'
import type { ReviewFilters, ReviewRow, WorkspaceLogin as Login } from '../types/workspace'

const TITLE = 'Process Discovery · Workspace'

export function Workspace({ mapRenderer }: { mapRenderer?: MapRenderer }) {
  const api = useApi()
  const queryClient = useQueryClient()
  const [login, setLogin] = useState<Login | null>(() => readWorkspaceToken())
  const [notice, setNotice] = useState<string | null>(null)
  const [filters, setFilters] = useState<ReviewFilters>(NO_FILTERS)
  const [filtersKey, setFiltersKey] = useState(0)
  const [openRow, setOpenRow] = useState<ReviewRow | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const regionRef = useRef<HTMLDivElement>(null)

  const signOut = useCallback(
    (message: string | null) => {
      clearWorkspaceToken()
      queryClient.removeQueries({ queryKey: ['workspace'] })
      setOpenRow(null)
      setStatus(null)
      setFilters(NO_FILTERS)
      setLogin(null)
      setNotice(message)
    },
    [queryClient],
  )
  const onSessionEnded = useCallback((error: unknown) => signOut(sessionEndedText(error)), [signOut])

  const list = useQuery({
    queryKey: ['workspace', 'sessions', filters],
    queryFn: () => watchSession(() => api.reviewList(filters), onSessionEnded),
    placeholderData: keepPreviousData,
    enabled: login !== null,
    retry: false,
  })
  const config = useQuery({ queryKey: ['config'], queryFn: () => api.getConfig(), staleTime: Infinity, retry: false })
  const workspaceOpen = config.data?.workspaceOpen === true
  const canDelete = config.isError || config.data?.workspaceOpen === false
  const taxonomy = useQuery({
    queryKey: ['workspace', 'taxonomy'],
    queryFn: () => api.getTaxonomy(),
    enabled: login !== null,
    staleTime: Infinity,
    retry: false,
  })


  const clearFilters = () => {
    setFilters(NO_FILTERS)
    setFiltersKey((k) => k + 1)
  }

  const onDeleted = async (message: string) => {
    setOpenRow(null)
    await list.refetch()
    setStatus(message)
    regionRef.current?.focus()
  }

  if (!login) {
    return (
      <div className="flex min-h-screen flex-col bg-page">
        <AppHeader title={TITLE} />
        <main className="flex-1">
          <WorkspaceLogin
            notice={notice}
            open={workspaceOpen}
            onLoggedIn={(l) => {
              setNotice(null)
              setLogin(l)
            }}
          />
        </main>
      </div>
    )
  }

  const filtered = Boolean(filters.status || filters.cluster || filters.q)
  let body
  if (list.isPending) {
    body = (
      <p role="status" className="flex items-center justify-center gap-2 p-10 text-sm text-muted">
        <Spinner /> Loading sessions…
      </p>
    )
  } else if (list.isError) {
    body = (
      <div className="flex flex-col items-start gap-3 py-6">
        <p role="alert" className="text-sm text-danger">
          {workspaceErrorText(list.error)}
        </p>
        <Button icon={<RotateCcw className="h-4 w-4" aria-hidden="true" />} onClick={() => void list.refetch()}>
          Retry
        </Button>
      </div>
    )
  } else {
    body = (
      <SessionTable
        data={list.data}
        busy={list.isPlaceholderData}
        onOpen={setOpenRow}
        onClearFilters={clearFilters}
        regionRef={regionRef}
      />
    )
  }

  return (
    <div className="flex min-h-screen flex-col bg-page">
      <AppHeader
        title={TITLE}
        actions={
          <>
            <span className="max-w-[7rem] truncate text-sm text-muted sm:max-w-[14rem]">Signed in as {login.name}</span>
            <Button aria-label="Refresh" icon={<RefreshCw className="h-4 w-4" aria-hidden="true" />} onClick={() => void list.refetch()}>
              <span className="hidden sm:inline">Refresh</span>
            </Button>
            <Button aria-label="Log out" icon={<LogOut className="h-4 w-4" aria-hidden="true" />} onClick={() => signOut(null)}>
              <span className="hidden sm:inline">Log out</span>
            </Button>
          </>
        }
      />
      <main className="mx-auto flex w-full min-w-0 max-w-[1400px] flex-1 flex-col gap-4 px-4 py-4">
        {list.data && !list.isError && <CountsLine data={list.data} filtered={filtered} />}
        <SessionFilters
          key={filtersKey}
          value={filters}
          onChange={setFilters}
          clusters={taxonomy.data?.clusters ?? []}
          clustersFailed={taxonomy.isError}
        />
        {status && (
          <Alert tone="info" onClose={() => setStatus(null)}>
            {status}
          </Alert>
        )}
        {body}
      </main>
      {openRow && (
        <SessionDialog
          key={openRow.id}
          row={openRow}
          mapRenderer={mapRenderer}
          canDelete={canDelete}
          onClose={(refresh) => {
            setOpenRow(null)
            if (refresh) void list.refetch()
          }}
          onDeleted={(message) => void onDeleted(message)}
          onSessionEnded={onSessionEnded}
        />
      )}
    </div>
  )
}
