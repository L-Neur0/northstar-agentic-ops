/**
 * React context that hands the `DiscoveryApi` instance to hooks and pages (spec 23 §3.12.1).
 * Why: tests and the fake mode inject an API through `ApiProvider` instead of module mocks, so the
 * same page code runs against the fake, a test double or the real HTTP client.
 * Rules: `useApi()` throws outside a provider, so a missing provider fails loudly in tests.
 */
import { createContext, useContext } from 'react'
import type { DiscoveryApi } from './api'

export const ApiContext = createContext<DiscoveryApi | null>(null)

export function useApi(): DiscoveryApi {
  const api = useContext(ApiContext)
  if (!api) throw new Error('useApi() needs an <ApiProvider>.')
  return api
}
