/**
 * Tests for the HTTP client of the interview side (spec 23 §3.12, §4, §12; AC-23.4, AC-23.5,
 * AC-23.59, AC-23.60).
 * Why: the real client is the only code that talks to spec 15's routes; each method must use the
 * method, path and body of the contract and turn every failure into one `ApiError` shape.
 * Rules: `fetch` is stubbed, and a fake `XMLHttpRequest` stands in for the upload; the visitor
 * key goes on every expert call and never on taxonomy or config.
 */
import { ApiError, createHttpApi } from './api'

type Call = [string, RequestInit]

function stubFetch(status = 200, body: unknown = {}, json = true) {
  const fn = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    text: async () => (json ? JSON.stringify(body) : String(body)),
  })
  vi.stubGlobal('fetch', fn)
  return fn
}

afterEach(() => vi.unstubAllGlobals())

const api = createHttpApi(() => 'Visitorkeyvisitorkey12')

describe('routes (AC-23.5)', () => {
  it.each<[string, () => Promise<unknown>, string, string, unknown]>([
    ['createSession', () => api.createSession({ displayName: 'Anna' }), 'POST', '/api/sessions', { displayName: 'Anna' }],
    ['listSessions', () => api.listSessions(), 'GET', '/api/sessions', undefined],
    ['getSession', () => api.getSession('s1'), 'GET', '/api/sessions/s1', undefined],
    ['deleteSession', () => api.deleteSession('s1'), 'DELETE', '/api/sessions/s1', undefined],
    ['sendMessage', () => api.sendMessage('s1', 'hello'), 'POST', '/api/sessions/s1/messages', { text: 'hello' }],
    ['confirm', () => api.confirm('s1', 'roles'), 'POST', '/api/sessions/s1/confirm', { target: 'roles' }],
    ['setCluster', () => api.setCluster('s1', 'FIN'), 'PUT', '/api/sessions/s1/cluster', { code: 'FIN' }],
    ['close', () => api.close('s1'), 'POST', '/api/sessions/s1/close', undefined],
    ['finish', () => api.finish('s1'), 'POST', '/api/sessions/s1/finish', undefined],
    ['listIdeas', () => api.listIdeas(), 'GET', '/api/ideas', undefined],
    ['startIdea', () => api.startIdea('i1'), 'POST', '/api/ideas/i1/start', undefined],
    ['deleteIdea', () => api.deleteIdea('i1'), 'DELETE', '/api/ideas/i1', undefined],
    ['deleteMyData', () => api.deleteMyData(), 'DELETE', '/api/me', undefined],
    ['getTaxonomy', () => api.getTaxonomy(), 'GET', '/api/taxonomy', undefined],
  ])('%s uses the contract', async (_name, call, method, path, body) => {
    const fetchFn = stubFetch()
    await call()
    const [url, init] = fetchFn.mock.calls[0] as Call
    expect(url).toBe(path)
    expect(init.method).toBe(method)
    expect(init.body === undefined ? undefined : JSON.parse(init.body as string)).toEqual(body)
  })

  it('omits an empty displayName on create', async () => {
    const fetchFn = stubFetch()
    await api.createSession({})
    expect(JSON.parse((fetchFn.mock.calls[0] as Call)[1].body as string)).toEqual({})
  })

  it('returns undefined on 204', async () => {
    stubFetch(204, '', false)
    await expect(api.deleteSession('s1')).resolves.toBeUndefined()
  })
})

describe('visitor key header (AC-23.4)', () => {
  it('is sent on expert calls and not on taxonomy', async () => {
    const fetchFn = stubFetch()
    await api.listSessions()
    await api.getTaxonomy()
    const headers = (i: number) => new Headers((fetchFn.mock.calls[i] as Call)[1].headers)
    expect(headers(0).get('X-Visitor-Key')).toBe('Visitorkeyvisitorkey12')
    expect(headers(1).get('X-Visitor-Key')).toBeNull()
  })
})

describe('errors (AC-23.5)', () => {
  it('parses {code, message, reason}', async () => {
    stubFetch(409, { code: 'map_incomplete', message: 'Not yet.', reason: 'below_gate' })
    const e = await api.finish('s1').catch((x: unknown) => x)
    expect(e).toBeInstanceOf(ApiError)
    expect(e).toMatchObject({ status: 409, code: 'map_incomplete', message: 'Not yet.', reason: 'below_gate' })
  })

  it('gives http_<status> on a non-JSON body', async () => {
    stubFetch(502, '<html>Bad gateway</html>', false)
    await expect(api.listSessions()).rejects.toMatchObject({ status: 502, code: 'http_502' })
  })

  it('gives network on a failed fetch', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(api.listSessions()).rejects.toMatchObject({ status: 0, code: 'network' })
  })
})

describe('document and report routes (AC-23.59)', () => {
  it.each<[string, () => Promise<unknown>, string, string, unknown]>([
    ['removeDocument', () => api.removeDocument('s1', 'd1'), 'DELETE', '/api/sessions/s1/documents/d1', undefined],
    ['confirmProposals', () => api.confirmProposals('s1', ['process.trigger']), 'POST', '/api/sessions/s1/proposals/confirm', { keys: ['process.trigger'] }],
    ['rejectProposals', () => api.rejectProposals('s1', ['process.trigger']), 'POST', '/api/sessions/s1/proposals/reject', { keys: ['process.trigger'] }],
    ['getReport', () => api.getReport('s1'), 'GET', '/api/sessions/s1/report', undefined],
    ['getConfig', () => api.getConfig(), 'GET', '/api/config', undefined],
  ])('%s uses the contract', async (_name, call, method, path, body) => {
    const fetchFn = stubFetch()
    await call()
    const [url, init] = fetchFn.mock.calls[0] as Call
    expect(url).toBe(path)
    expect(init.method).toBe(method)
    expect(init.body === undefined ? undefined : JSON.parse(init.body as string)).toEqual(body)
    expect(new Headers(init.headers).get('X-Visitor-Key')).toBe(path === '/api/config' ? null : 'Visitorkeyvisitorkey12')
  })
})

/** A stand-in for `XMLHttpRequest` that records the request and lets the test answer it. */
class FakeXhr {
  static last: FakeXhr | null = null
  method = ''
  url = ''
  headers: Record<string, string> = {}
  body: FormData | null = null
  status = 0
  responseText = ''
  upload: { onprogress: ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = { onprogress: null }
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  constructor() {
    FakeXhr.last = this
  }
  open(method: string, url: string) {
    this.method = method
    this.url = url
  }
  setRequestHeader(name: string, value: string) {
    this.headers[name] = value
  }
  send(body: FormData) {
    this.body = body
  }
  reply(status: number, text: string) {
    this.status = status
    this.responseText = text
    this.onload?.()
  }
}

describe('uploadDocument over XHR (AC-23.59)', () => {
  beforeEach(() => vi.stubGlobal('XMLHttpRequest', FakeXhr))
  const file = () => new File(['hello'], 'procedure.docx')

  it('posts one multipart file part with the key and reports progress', async () => {
    const progress = vi.fn()
    const pending = api.uploadDocument('s1', file(), progress)
    const xhr = FakeXhr.last!
    expect(xhr.method).toBe('POST')
    expect(xhr.url).toBe('/api/sessions/s1/documents')
    expect(xhr.headers['X-Visitor-Key']).toBe('Visitorkeyvisitorkey12')
    expect(xhr.headers['Content-Type']).toBeUndefined()
    expect([...xhr.body!.keys()]).toEqual(['file'])
    expect((xhr.body!.get('file') as File).name).toBe('procedure.docx')
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 31, total: 50 })
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 50, total: 50 })
    expect(progress.mock.calls).toEqual([[62], [100]])
    xhr.reply(201, JSON.stringify({ session: {}, document: {}, report: { message: 'ok' } }))
    await expect(pending).resolves.toMatchObject({ report: { message: 'ok' } })
  })

  it('parses {code, message}, a non-JSON body and a network failure into ApiError', async () => {
    let pending = api.uploadDocument('s1', file())
    FakeXhr.last!.reply(415, JSON.stringify({ code: 'document_type', message: "This file type can't be read." }))
    await expect(pending).rejects.toMatchObject({ status: 415, code: 'document_type', message: "This file type can't be read." })

    pending = api.uploadDocument('s1', file())
    FakeXhr.last!.reply(413, '<html>Request Entity Too Large</html>')
    await expect(pending).rejects.toMatchObject({ status: 413, code: 'http_413' })

    pending = api.uploadDocument('s1', file())
    FakeXhr.last!.onerror?.()
    await expect(pending).rejects.toMatchObject({ status: 0, code: 'network' })
  })
})

describe('getReportPdf (AC-23.59, AC-23.60)', () => {
  function stubPdf(disposition: string | null, status = 200) {
    const fn = vi.fn().mockResolvedValue({
      ok: status === 200,
      status,
      headers: new Headers(disposition ? { 'Content-Disposition': disposition } : {}),
      blob: async () => new Blob(['%PDF-1.4'], { type: 'application/pdf' }),
      text: async () => JSON.stringify({ code: 'report_not_ready', message: 'The report is ready once the map is finished.' }),
    })
    vi.stubGlobal('fetch', fn)
    return fn
  }

  it('fetches with the visitor key and takes the file name from Content-Disposition', async () => {
    const fn = stubPdf('attachment; filename="discovery-report-monthly-cost-review.pdf"')
    const { blob, filename } = await api.getReportPdf('s1')
    const [url, init] = fn.mock.calls[0] as Call
    expect(url).toBe('/api/sessions/s1/report.pdf')
    expect(new Headers(init.headers).get('X-Visitor-Key')).toBe('Visitorkeyvisitorkey12')
    expect(filename).toBe('discovery-report-monthly-cost-review.pdf')
    expect(await blob.text()).toContain('%PDF')
  })

  it('falls back to discovery-report.pdf without the header', async () => {
    stubPdf(null)
    expect((await api.getReportPdf('s1')).filename).toBe('discovery-report.pdf')
  })

  it('turns an error reply into ApiError', async () => {
    stubPdf(null, 409)
    await expect(api.getReportPdf('s1')).rejects.toMatchObject({ status: 409, code: 'report_not_ready' })
  })
})

describe('workspace calls (spec 23 part 3; AC-23.111, AC-23.112)', () => {
  const ws = createHttpApi(() => 'Visitorkeyvisitorkey12', () => 'tok.en')
  const headersOf = (fn: ReturnType<typeof stubFetch>) => (fn.mock.calls[0] as Call)[1].headers as Record<string, string>

  it.each<[string, () => Promise<unknown>, string, string]>([
    ['reviewList (no filters)', () => ws.reviewList({ status: null, cluster: null, q: '  ' }), 'GET', '/api/review/sessions'],
    [
      'reviewList (all filters)',
      () => ws.reviewList({ status: 'finished', cluster: 'FIN', q: ' cost ' }),
      'GET',
      '/api/review/sessions?status=finished&cluster=FIN&q=cost',
    ],
    ['reviewSession', () => ws.reviewSession('s 1'), 'GET', '/api/review/sessions/s%201'],
    ['reviewConversation', () => ws.reviewConversation('s1'), 'GET', '/api/review/sessions/s1/conversation'],
    ['deleteReviewSession', () => ws.deleteReviewSession('s1', '"e7"'), 'DELETE', '/api/review/sessions/s1'],
  ])('%s: path, bearer token, no visitor key', async (_name, call, method, path) => {
    const fetchFn = stubFetch()
    await call()
    const [url, init] = fetchFn.mock.calls[0] as Call
    expect(url).toBe(path)
    expect(init.method).toBe(method)
    expect(headersOf(fetchFn).Authorization).toBe('Bearer tok.en')
    expect(headersOf(fetchFn)['X-Visitor-Key']).toBeUndefined()
  })

  it('delete sends If-Match with the etag', async () => {
    const fetchFn = stubFetch(204, '', false)
    await ws.deleteReviewSession('s1', '"e7"')
    expect(headersOf(fetchFn)['If-Match']).toBe('"e7"')
  })

  it('login posts code and name, without token or visitor key', async () => {
    const fetchFn = stubFetch(200, { token: 't', role: 'specialist', name: 'Maria', expiresAt: 'x' })
    await ws.workspaceLogin('demo-specialist', 'Maria')
    const [url, init] = fetchFn.mock.calls[0] as Call
    expect(url).toBe('/api/workspace/login')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual({ code: 'demo-specialist', name: 'Maria' })
    expect(headersOf(fetchFn).Authorization).toBeUndefined()
    expect(headersOf(fetchFn)['X-Visitor-Key']).toBeUndefined()
  })

  it('expert calls never send the token', async () => {
    const fetchFn = stubFetch()
    await ws.listSessions()
    expect(headersOf(fetchFn).Authorization).toBeUndefined()
    expect(headersOf(fetchFn)['X-Visitor-Key']).toBe('Visitorkeyvisitorkey12')
  })

  it('a workspace call without a token fails with 401 workspace_code_required and sends nothing', async () => {
    const fetchFn = stubFetch()
    const none = createHttpApi(() => 'Visitorkeyvisitorkey12', () => null)
    for (const call of [
      () => none.reviewList({ status: null, cluster: null, q: '' }),
      () => none.reviewSession('s1'),
      () => none.reviewConversation('s1'),
      () => none.getReviewReportPdf('s1'),
      () => none.deleteReviewSession('s1', 'e'),
    ]) {
      await expect(call()).rejects.toMatchObject({ status: 401, code: 'workspace_code_required' })
    }
    expect(fetchFn).not.toHaveBeenCalled()
  })

  it('getReviewReportPdf returns the blob and the Content-Disposition name, with the bearer token', async () => {
    const blob = new Blob(['%PDF'])
    const fetchFn = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      blob: async () => blob,
      headers: new Headers({ 'Content-Disposition': 'attachment; filename="discovery-report-cost.pdf"' }),
    })
    vi.stubGlobal('fetch', fetchFn)
    const out = await ws.getReviewReportPdf('s1')
    expect(out).toEqual({ blob, filename: 'discovery-report-cost.pdf' })
    const [url, init] = fetchFn.mock.calls[0] as Call
    expect(url).toBe('/api/review/sessions/s1/report.pdf')
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok.en')
    expect((init.headers as Record<string, string>)['X-Visitor-Key']).toBeUndefined()
  })

  it('getReviewReportPdf falls back to discovery-report.pdf without the header', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, status: 200, blob: async () => new Blob(['x']), headers: new Headers() }),
    )
    expect((await ws.getReviewReportPdf('s1')).filename).toBe('discovery-report.pdf')
  })

  it('a 409 report_not_ready becomes an ApiError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 409, text: async () => JSON.stringify({ code: 'report_not_ready', message: 'm' }) }),
    )
    await expect(ws.getReviewReportPdf('s1')).rejects.toBeInstanceOf(ApiError)
  })
})
