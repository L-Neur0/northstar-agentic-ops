/**
 * Test helper that renders a tree inside the app's providers (spec 23 §7).
 * Why: pages and some components need React Query, the router and an `ApiProvider`; this wraps
 * them once, with retries off so failures show at once, and an injected API (default: the fake
 * with no delay and no storage).
 * Rules: test-only; must not be imported by application code.
 */
import { render } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import type { ReactElement } from 'react'
import { ApiProvider } from '../services/ApiProvider'
import { createFakeApi } from '../services/fakeApi'
import type { DiscoveryApi } from '../services/api'

export function renderWithProviders(
  ui: ReactElement,
  { api = createFakeApi({ delayMs: 0, persist: false }), route = '/' }: { api?: DiscoveryApi; route?: string } = {},
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const result = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <ApiProvider api={api}>{ui}</ApiProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { ...result, api, client }
}
