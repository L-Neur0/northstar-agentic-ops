/**
 * Chooses the `DiscoveryApi` for the running app (spec 23 §3.12.3).
 * Why: one place decides between the real HTTP client and the fake. The fake is loaded by dynamic
 * import behind a build-time constant, so a normal build drops it entirely (AC-23.48).
 * Rules: the HTTP client reads the visitor key per request; nothing here logs the key.
 */
import { createHttpApi, type DiscoveryApi } from './api'
import { getVisitorKey } from '../access/visitorKey'

export async function loadApi(): Promise<DiscoveryApi> {
  if (import.meta.env.VITE_API_MODE === 'fake') {
    const { createFakeApi } = await import('./fakeApi')
    return createFakeApi()
  }
  return createHttpApi(getVisitorKey)
}
