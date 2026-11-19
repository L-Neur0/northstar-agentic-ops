/**
 * The `DiscoveryApi` interface and its HTTP implementation (spec 23 §3.12, §4; AC-23.4, AC-23.5).
 * Why: pages and hooks talk to one interface, so tests and the fake mode can swap in
 * `createFakeApi()` without module mocks, and the real client covers spec 15 part 2 routes 1–14.
 * Rules: same origin (`/api/...`), camelCase JSON, `X-Visitor-Key` on every expert route but never
 * on `/api/taxonomy`; every failure becomes one `ApiError{status, code, message, reason?}`.
 * Must not: log or put the visitor key in an error, or build any profile logic.
 */
import type {
  ConfirmTarget,
  DeletedCounts,
  Idea,
  SessionOut,
  SessionSummary,
  Taxonomy,
  TurnOut,
} from '../types/process-discovery'

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
}

async function request<T>(
  method: string,
  path: string,
  options: { body?: unknown; key?: string } = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  if (options.key) headers['X-Visitor-Key'] = options.key

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

  if (!response.ok) {
    const body = parsed && typeof data === 'object' && data !== null ? (data as Record<string, unknown>) : null
    if (body && typeof body.code === 'string') {
      throw new ApiError(
        response.status,
        body.code,
        typeof body.message === 'string' ? body.message : '',
        typeof body.reason === 'string' ? body.reason : undefined,
      )
    }
    throw new ApiError(response.status, `http_${response.status}`, `HTTP ${response.status}`)
  }
  return data as T
}

/** The real client. `getKey` is called per request, so a resume link takes effect at once. */
export function createHttpApi(getKey: () => string): DiscoveryApi {
  const expert = <T>(method: string, path: string, body?: unknown) =>
    request<T>(method, path, { body, key: getKey() })
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
  }
}
