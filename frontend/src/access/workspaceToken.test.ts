/**
 * Tests for the workspace token store (spec 23 §19.2; AC-23.106, AC-23.108, AC-23.110).
 * Why: the token decides whether the workspace shows the login or the list, so a stale, malformed
 * or engineer token must never open the list, and blocked storage must not break login.
 * What: round trip under `pd_workspace` in sessionStorage, expiry and malformed values removed,
 * the code never stored, a memory fallback when storage throws.
 * Must not: touch localStorage except to prove it stays empty.
 */
import { WORKSPACE_TOKEN_KEY, clearWorkspaceToken, readWorkspaceToken, storeWorkspaceToken } from './workspaceToken'

const future = new Date(Date.now() + 3_600_000).toISOString()
const login = { token: 'fake.specialist', role: 'specialist' as const, name: 'Maria', expiresAt: future }

afterEach(() => {
  vi.restoreAllMocks()
  clearWorkspaceToken()
  sessionStorage.clear()
  localStorage.clear()
})

describe('workspace token (AC-23.106, AC-23.108)', () => {
  it('stores {token, role, name, expiresAt} in sessionStorage only and reads it back', () => {
    storeWorkspaceToken(login)
    expect(JSON.parse(sessionStorage.getItem(WORKSPACE_TOKEN_KEY)!)).toEqual(login)
    expect(localStorage.length).toBe(0)
    expect(readWorkspaceToken()).toEqual(login)
  })

  it('never stores anything but the four fields (no code)', () => {
    storeWorkspaceToken({ ...login, code: 'demo-specialist' } as never)
    expect(sessionStorage.getItem(WORKSPACE_TOKEN_KEY)).not.toContain('demo-specialist')
  })

  it.each([
    ['expired', JSON.stringify({ ...login, expiresAt: new Date(Date.now() - 1000).toISOString() })],
    ['malformed', '{not json'],
    ['engineer', JSON.stringify({ ...login, role: 'engineer' })],
    ['no token', JSON.stringify({ ...login, token: '' })],
  ])('removes an %s value and returns null', (_name, raw) => {
    sessionStorage.setItem(WORKSPACE_TOKEN_KEY, raw)
    expect(readWorkspaceToken()).toBeNull()
    expect(sessionStorage.getItem(WORKSPACE_TOKEN_KEY)).toBeNull()
  })

  it('returns null with nothing stored', () => {
    expect(readWorkspaceToken()).toBeNull()
  })

  it('clear removes the token', () => {
    storeWorkspaceToken(login)
    clearWorkspaceToken()
    expect(readWorkspaceToken()).toBeNull()
  })
})

describe('blocked storage (AC-23.110)', () => {
  it('keeps the token in memory for the tab when sessionStorage throws', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError')
    })
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError')
    })
    storeWorkspaceToken(login)
    expect(readWorkspaceToken()).toEqual(login)
  })
})
