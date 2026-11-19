/**
 * Provider of the `DiscoveryApi` instance (spec 23 §3.1.1, §3.12.1).
 * Why: `main.tsx` wraps the app in it with the HTTP client or, in fake mode, the in-memory fake;
 * tests wrap pages in it with a fake of their own.
 * Rules: holds no state of its own; the instance is chosen once by the caller.
 */
import type { ReactNode } from 'react'
import { ApiContext } from './apiContext'
import type { DiscoveryApi } from './api'

export function ApiProvider({ api, children }: { api: DiscoveryApi; children: ReactNode }) {
  return <ApiContext.Provider value={api}>{children}</ApiContext.Provider>
}
