/**
 * Tests for the API mode switch and its build guard (spec 23 §3.12.3; AC-23.48).
 * Why: the fake API is for local development and demos; a production bundle must never ship it,
 * so the Vite config refuses a build with `VITE_API_MODE=fake`.
 * Rules: anything other than "fake" means the real HTTP client.
 */
import { assertBuildAllowed, resolveApiMode } from './apiMode'

describe('API mode (AC-23.48)', () => {
  it('defaults to http and accepts fake', () => {
    expect(resolveApiMode(undefined)).toBe('http')
    expect(resolveApiMode('http')).toBe('http')
    expect(resolveApiMode('fake')).toBe('fake')
    expect(resolveApiMode('FAKE ')).toBe('fake')
  })

  it('fails a build in fake mode and allows the dev server', () => {
    expect(() => assertBuildAllowed('build', 'fake')).toThrow(/VITE_API_MODE=fake/)
    expect(() => assertBuildAllowed('build', 'http')).not.toThrow()
    expect(() => assertBuildAllowed('serve', 'fake')).not.toThrow()
  })
})
