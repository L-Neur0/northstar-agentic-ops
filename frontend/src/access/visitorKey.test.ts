/**
 * Tests for the visitor key and the private resume link (spec 23 §3.2, spec 16 §3.1; AC-23.1–23.3).
 * Why: the key is the expert's only identity; losing or leaking it loses their sessions.
 * Rules: 22-character URL-safe key in `localStorage`, memory fallback when storage throws, a
 * resume fragment is consumed once and removed from the URL.
 */
import {
  VISITOR_KEY_STORAGE,
  consumeResumeFragment,
  getVisitorKey,
  isStorageAvailable,
  resetVisitorKeyForTests,
  resumeLink,
  takeAccessNotice,
} from './visitorKey'

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
  resetVisitorKeyForTests()
  window.history.replaceState(null, '', '/')
})

describe('visitor key', () => {
  it('creates one 22-character URL-safe key and keeps it (AC-23.1)', () => {
    const a = getVisitorKey()
    const b = getVisitorKey()
    expect(a).toMatch(/^[A-Za-z0-9_-]{22}$/)
    expect(b).toBe(a)
    expect(localStorage.getItem(VISITOR_KEY_STORAGE)).toBe(a)
  })

  it('falls back to a memory key when storage throws (AC-23.2)', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    const a = getVisitorKey()
    expect(a).toMatch(/^[A-Za-z0-9_-]{22}$/)
    expect(getVisitorKey()).toBe(a)
    expect(isStorageAvailable()).toBe(false)
  })

  it('builds the resume link from the origin and the key', () => {
    const key = getVisitorKey()
    expect(resumeLink()).toBe(`${window.location.origin}/#k=${key}`)
  })
})

describe('resume fragment (AC-23.3)', () => {
  it('stores a valid key, removes the fragment and sets the notice', () => {
    const key = 'Abcdefghijklmnopqrstu_'
    window.history.replaceState(null, '', `/#k=${key}`)
    consumeResumeFragment()
    expect(localStorage.getItem(VISITOR_KEY_STORAGE)).toBe(key)
    expect(window.location.hash).toBe('')
    expect(getVisitorKey()).toBe(key)
    expect(takeAccessNotice()).toBe('You opened a resume link. You now see the processes saved with it.')
    expect(takeAccessNotice()).toBeNull()
  })

  it('removes an invalid value and says so', () => {
    localStorage.setItem(VISITOR_KEY_STORAGE, 'Existingkeyexistingkey')
    window.history.replaceState(null, '', '/#k=bad!')
    consumeResumeFragment()
    expect(window.location.hash).toBe('')
    expect(localStorage.getItem(VISITOR_KEY_STORAGE)).toBe('Existingkeyexistingkey')
    expect(takeAccessNotice()).toBe('This resume link is not valid.')
  })

  it('does nothing without a fragment', () => {
    consumeResumeFragment()
    expect(takeAccessNotice()).toBeNull()
  })
})
