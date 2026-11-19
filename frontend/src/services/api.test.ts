/**
 * Tests for the HTTP client of the interview side (spec 23 §3.12, §4; AC-23.4, AC-23.5).
 * Why: the real client is the only code that talks to spec 15's routes; each method must use the
 * method, path and body of the contract and turn every failure into one `ApiError` shape.
 * Rules: `fetch` is stubbed; the visitor key goes on every expert call and never on taxonomy.
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
