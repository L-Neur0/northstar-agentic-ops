/**
 * Route tests of the app shell (spec 23 §3.1; AC-23.6).
 * Why: replaces the scaffold test. Every route renders its page under the same header,
 * "AI Use Case Discovery Agent", with no logo; an unknown path goes back to My processes.
 * Rules: rendered with the fake API (no delay, no storage) inside the shared test providers.
 */
import { screen, within } from '@testing-library/react'
import App from './App'
import { renderWithProviders } from './test/render'
import { INTRO_SEEN_KEY } from './components/process-discovery/introStorage'

beforeEach(() => localStorage.setItem(INTRO_SEEN_KEY, 'true'))
afterEach(() => localStorage.clear())

describe('routes (AC-23.6)', () => {
  it.each([
    ['/', 'My processes'],
    ['/process-discovery', 'Discovery conversation'],
    ['/process-discovery/abc', 'Discovery conversation'],
    ['/report/abc', 'Back to My processes'],
    ['/nowhere', 'My processes'],
  ])('%s renders its page under the plain header', async (route, landmark) => {
    renderWithProviders(<App />, { route })
    expect(screen.getByRole('heading', { level: 1, name: 'AI Use Case Discovery Agent' })).toBeInTheDocument()
    if (landmark === 'Discovery conversation') {
      expect(await screen.findByRole('region', { name: landmark })).toBeInTheDocument()
    } else {
      expect(await screen.findAllByText(landmark)).not.toHaveLength(0)
    }
    expect(document.querySelector('img')).toBeNull()
  })
})

describe('product name (renamed 2026-11-21)', () => {
  it('shows the full name, a short form under the sm breakpoint, and the tagline on Home', async () => {
    renderWithProviders(<App />, { route: '/' })
    const h1 = screen.getByRole('heading', { level: 1, name: 'AI Use Case Discovery Agent' })
    expect(within(h1).getByText('AI Use Case Discovery Agent')).toHaveClass('hidden', 'sm:inline')
    expect(within(h1).getByText('Use Case Discovery')).toHaveClass('sm:hidden')
    expect(await screen.findByText('Find a workflow worth transforming, map it step by step, and see where AI can help')).toBeInTheDocument()
  })
})

describe('workspace route (spec 23 §19.1)', () => {
  it('/workspace renders the workspace page with its login', () => {
    renderWithProviders(<App />, { route: '/workspace' })
    expect(screen.getByRole('heading', { level: 1, name: 'AI Use Case Discovery Agent · Workspace' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Open workspace' })).toBeInTheDocument()
  })

  it('no expert screen links to /workspace', () => {
    renderWithProviders(<App />, { route: '/' })
    expect(document.querySelector('a[href*="workspace"]')).toBeNull()
  })
})
