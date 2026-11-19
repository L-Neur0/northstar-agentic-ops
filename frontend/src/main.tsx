/**
 * Frontend entry point (spec 23 §3.1.1).
 * Why: consumes a resume link fragment (`#k=<key>`) before the first render so the first API call
 * already uses that key, then mounts React Query (retry 1, no refetch on focus), the router, the
 * API provider (HTTP client, or the fake in fake mode) and the app.
 * Rules: nothing else belongs here; the visitor key is never logged.
 */
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import { ApiProvider } from './services/ApiProvider'
import { loadApi } from './services/loadApi'
import { consumeResumeFragment } from './access/visitorKey'
import './index.css'

consumeResumeFragment()

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } })

void loadApi().then((api) => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <ApiProvider api={api}>
            <App />
          </ApiProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </StrictMode>,
  )
})
