/**
 * The `DiscoveryApi` interface and its HTTP implementation (spec 23 §3.12, §4, §12; AC-23.4,
 * AC-23.5, AC-23.59, AC-23.60).
 * Why: pages and hooks talk to one interface, so tests and the fake mode can swap in
 * `createFakeApi()` without module mocks, and the real client covers spec 15 part 2 routes 1–14,
 * the document routes of spec 17 and the report routes of spec 20 §3.5.
 * Rules: same origin (`/api/...`), camelCase JSON, `X-Visitor-Key` on every expert route but never
 * on `/api/taxonomy` or `/api/config`; every failure becomes one `ApiError{status, code, message,
 * reason?}`. The upload uses `XMLHttpRequest` because only XHR reports upload progress; the PDF is
 * fetched (not linked) so it carries the visitor key.
 * Part 3 (spec 23 §20; AC-23.111, AC-23.112): the workspace calls of spec 21 send
 * `Authorization: Bearer <token>` (read per request) and never the visitor key; expert calls never
 * send the token; a workspace call without a token fails locally with 401
 * `workspace_code_required` and sends nothing; delete sends `If-Match`.
 * Must not: log or put the visitor key or the token in an error, read a file's content, or build
 * any profile logic.
 */
import type { DiscoveryReport } from '../types/report'
import type {
  ConfirmTarget,
  DeletedCounts,
  DocumentUploadOut,
  PublicConfig,
  Idea,
  SessionOut,
  SessionSummary,
  Taxonomy,
  TurnOut,
} from '../types/process-discovery'
import type { ConversationOut, ReviewFilters, ReviewListOut, ReviewSessionOut, WorkspaceLogin } from '../types/workspace'
import { readWorkspaceToken } from '../access/workspaceToken'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly reason?: string

  constructor(status: number, code: string, message: string, reason?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.reason = reason
  }
}

export interface DiscoveryApi {
  createSession(body: { displayName?: string; fromIdeaId?: string }): Promise<SessionOut>
  listSessions(): Promise<{ sessions: SessionSummary[] }>
  getSession(id: string): Promise<SessionOut>
  deleteSession(id: string): Promise<void>
  sendMessage(id: string, text: string): Promise<TurnOut>
  confirm(id: string, target: ConfirmTarget): Promise<SessionOut>
  setCluster(id: string, code: string): Promise<SessionOut>
  close(id: string): Promise<SessionOut>
  finish(id: string): Promise<SessionOut>
  listIdeas(): Promise<{ ideas: Idea[] }>
  startIdea(id: string): Promise<SessionOut>
  deleteIdea(id: string): Promise<void>
  deleteMyData(): Promise<DeletedCounts>
  getTaxonomy(): Promise<Taxonomy>
  getConfig(): Promise<PublicConfig>
  uploadDocument(id: string, file: File, onProgress?: (percent: number) => void): Promise<DocumentUploadOut>
  removeDocument(id: string, docId: string): Promise<SessionOut>
  confirmProposals(id: string, keys: string[]): Promise<SessionOut>
  rejectProposals(id: string, keys: string[]): Promise<SessionOut>
  getReport(id: string): Promise<DiscoveryReport>
  getReportPdf(id: string): Promise<{ blob: Blob; filename: string }>
  workspaceLogin(code: string, name: string): Promise<WorkspaceLogin>
  reviewList(filters: ReviewFilters): Promise<ReviewListOut>
  reviewSession(id: string): Promise<ReviewSessionOut>
  reviewConversation(id: string): Promise<ConversationOut>
  getReviewReportPdf(id: string): Promise<{ blob: Blob; filename: string }>
  deleteReviewSession(id: string, etag: string): Promise<void>
}

/** The local refusal of a workspace call made without a token (nothing is sent). */
export const noWorkspaceToken = () =>
  new ApiError(401, 'workspace_code_required', 'Enter the workspace access code.')

/** The query string of the list: empty filters are left out (spec 23 §19.3). */
export function reviewQuery(filters: ReviewFilters): string {
  const params = new URLSearchParams()
  if (filters.status) params.set('status', filters.status)
  if (filters.cluster) params.set('cluster', filters.cluster)
  if (filters.q.trim()) params.set('q', filters.q.trim())
  const text = params.toString()
  return text ? `?${text}` : ''
}

/** Turns a failed reply's status and body text into the one `ApiError` shape. */
function toApiError(status: number, text: string): ApiError {
  let body: Record<string, unknown> | null = null
  try {
    const data: unknown = JSON.parse(text)
    if (typeof data === 'object' && data !== null) body = data as Record<string, unknown>
  } catch {
    body = null
  }
  if (body && typeof body.code === 'string') {
    return new ApiError(
      status,
      body.code,
      typeof body.message === 'string' ? body.message : '',
      typeof body.reason === 'string' ? body.reason : undefined,
    )
  }
  return new ApiError(status, `http_${status}`, `HTTP ${status}`)
}

export const DEFAULT_PDF_NAME = 'discovery-report.pdf'

/** The file name of a `Content-Disposition` header, or the default name. */
export function filenameFrom(header: string | null): string {
  const match = header ? /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(header) : null
  return match ? decodeURIComponent(match[1].trim()) : DEFAULT_PDF_NAME
}

/** Multipart upload of one `file` part with upload progress (spec 23 §12 "Upload transport"). */
function uploadWithProgress(
  path: string,
  file: File,
  key: string,
  onProgress?: (percent: number) => void,
): Promise<DocumentUploadOut> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', path)
    xhr.setRequestHeader('Accept', 'application/json')
    xhr.setRequestHeader('X-Visitor-Key', key)
    xhr.upload.onprogress = (e: ProgressEvent) => {
      if (e.lengthComputable && e.total > 0) onProgress?.(Math.round((e.loaded / e.total) * 100))
    }
    xhr.onerror = () => reject(new ApiError(0, 'network', 'Could not reach the server.'))
    xhr.onload = () => {
      const text = typeof xhr.responseText === 'string' ? xhr.responseText : ''
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(text) as DocumentUploadOut)
        } catch {
          reject(new ApiError(xhr.status, `http_${xhr.status}`, `HTTP ${xhr.status}`))
        }
      } else {
        reject(toApiError(xhr.status, text))
      }
    }
    const form = new FormData()
    form.append('file', file, file.name)
    xhr.send(form)
  })
}

async function request<T>(
  method: string,
  path: string,
  options: { body?: unknown; key?: string; auth?: string; ifMatch?: string } = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  if (options.key) headers['X-Visitor-Key'] = options.key
  if (options.auth) headers.Authorization = `Bearer ${options.auth}`
  if (options.ifMatch) headers['If-Match'] = options.ifMatch

  let response: Response
  try {
    response = await fetch(path, {
      method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    })
  } catch {
    throw new ApiError(0, 'network', 'Could not reach the server.')
  }

  const text = response.status === 204 ? '' : await response.text()
  let data: unknown = undefined
  let parsed = false
  if (text) {
    try {
      data = JSON.parse(text)
      parsed = true
    } catch {
      parsed = false
    }
  }

  if (!response.ok) throw toApiError(response.status, parsed ? text : '')
  return data as T
}

/** A file download: the blob and the `Content-Disposition` name (report PDFs, both sides). */
async function fetchBlob(path: string, headers: Record<string, string>): Promise<{ blob: Blob; filename: string }> {
  let response: Response
  try {
    response = await fetch(path, { method: 'GET', headers: { Accept: 'application/pdf', ...headers } })
  } catch {
    throw new ApiError(0, 'network', 'Could not reach the server.')
  }
  if (!response.ok) throw toApiError(response.status, await response.text())
  return { blob: await response.blob(), filename: filenameFrom(response.headers.get('Content-Disposition')) }
}

/**
 * The real client. `getKey` and `getToken` are called per request, so a resume link or a new
 * workspace login takes effect at once.
 */
export function createHttpApi(
  getKey: () => string,
  getToken: () => string | null = () => readWorkspaceToken()?.token ?? null,
): DiscoveryApi {
  const expert = <T>(method: string, path: string, body?: unknown) =>
    request<T>(method, path, { body, key: getKey() })
  const bearer = () => {
    const token = getToken()
    if (!token) throw noWorkspaceToken()
    return token
  }
  const workspace = async <T>(method: string, path: string, ifMatch?: string) =>
    request<T>(method, path, { auth: bearer(), ifMatch })
  const id = encodeURIComponent

  return {
    createSession: ({ displayName, fromIdeaId }) =>
      expert('POST', '/api/sessions', {
        ...(displayName ? { displayName } : {}),
        ...(fromIdeaId ? { fromIdeaId } : {}),
      }),
    listSessions: () => expert('GET', '/api/sessions'),
    getSession: (s) => expert('GET', `/api/sessions/${id(s)}`),
    deleteSession: (s) => expert('DELETE', `/api/sessions/${id(s)}`),
    sendMessage: (s, text) => expert('POST', `/api/sessions/${id(s)}/messages`, { text }),
    confirm: (s, target) => expert('POST', `/api/sessions/${id(s)}/confirm`, { target }),
    setCluster: (s, code) => expert('PUT', `/api/sessions/${id(s)}/cluster`, { code }),
    close: (s) => expert('POST', `/api/sessions/${id(s)}/close`),
    finish: (s) => expert('POST', `/api/sessions/${id(s)}/finish`),
    listIdeas: () => expert('GET', '/api/ideas'),
    startIdea: (i) => expert('POST', `/api/ideas/${id(i)}/start`),
    deleteIdea: (i) => expert('DELETE', `/api/ideas/${id(i)}`),
    deleteMyData: () => expert('DELETE', '/api/me'),
    getTaxonomy: () => request('GET', '/api/taxonomy'),
    getConfig: () => request('GET', '/api/config'),
    uploadDocument: (s, file, onProgress) => uploadWithProgress(`/api/sessions/${id(s)}/documents`, file, getKey(), onProgress),
    removeDocument: (s, d) => expert('DELETE', `/api/sessions/${id(s)}/documents/${id(d)}`),
    confirmProposals: (s, keys) => expert('POST', `/api/sessions/${id(s)}/proposals/confirm`, { keys }),
    rejectProposals: (s, keys) => expert('POST', `/api/sessions/${id(s)}/proposals/reject`, { keys }),
    getReport: (s) => expert('GET', `/api/sessions/${id(s)}/report`),
    getReportPdf: (s) => fetchBlob(`/api/sessions/${id(s)}/report.pdf`, { 'X-Visitor-Key': getKey() }),
    workspaceLogin: (code, name) => request('POST', '/api/workspace/login', { body: { code, name } }),
    reviewList: (filters) => workspace('GET', `/api/review/sessions${reviewQuery(filters)}`),
    reviewSession: (s) => workspace('GET', `/api/review/sessions/${id(s)}`),
    reviewConversation: (s) => workspace('GET', `/api/review/sessions/${id(s)}/conversation`),
    getReviewReportPdf: async (s) =>
      fetchBlob(`/api/review/sessions/${id(s)}/report.pdf`, { Authorization: `Bearer ${bearer()}` }),
    deleteReviewSession: (s, etag) => workspace('DELETE', `/api/review/sessions/${id(s)}`, etag),
  }
}
