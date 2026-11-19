/**
 * Tests for the light and dark theme logic and its header toggle (spec 23 §3.13; AC-23.52 to
 * AC-23.56).
 * Why: the theme must start right (stored choice, else the system setting), switch with one press,
 * follow the system live only while nothing is stored, and survive blocked storage.
 * What: drives `AppHeader` with a fake `matchMedia`, checks the `dark` class on `<html>` and the
 * stored `pd_theme`, and runs the inline script of `index.html` against fakes.
 * Must not: rely on a real browser setting; every test installs its own fake and cleans up.
 */
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import indexHtml from '../../index.html?raw'
import { AppHeader } from '../components/layout/AppHeader'
import { THEME_STORAGE_KEY } from './theme'

type Listener = (e: { matches: boolean }) => void

/** A fake `prefers-color-scheme: dark` query whose answer the test can change. */
function fakeSystem(dark: boolean) {
  const listeners = new Set<Listener>()
  const mql = {
    matches: dark,
    media: '(prefers-color-scheme: dark)',
    addEventListener: (_: string, l: Listener) => listeners.add(l),
    removeEventListener: (_: string, l: Listener) => listeners.delete(l),
  }
  window.matchMedia = vi.fn(() => mql) as unknown as typeof window.matchMedia
  return {
    set(next: boolean) {
      mql.matches = next
      act(() => listeners.forEach((l) => l({ matches: next })))
    },
  }
}

const isDark = () => document.documentElement.classList.contains('dark')

afterEach(() => {
  localStorage.clear()
  document.documentElement.classList.remove('dark')
  vi.restoreAllMocks()
})

describe('theme toggle in the header (AC-23.52, AC-23.53)', () => {
  it('shows a moon in light mode and a sun in dark mode with the matching label and aria-pressed', async () => {
    fakeSystem(false)
    render(<AppHeader />)
    const button = screen.getByRole('button', { name: 'Switch to dark theme' })
    expect(button).toHaveAttribute('title', 'Switch to dark theme')
    expect(button).toHaveAttribute('aria-pressed', 'false')
    expect(button.querySelector('.lucide-moon')).not.toBeNull()

    await userEvent.click(button)
    const after = screen.getByRole('button', { name: 'Switch to light theme' })
    expect(after).toHaveAttribute('title', 'Switch to light theme')
    expect(after).toHaveAttribute('aria-pressed', 'true')
    expect(after.querySelector('.lucide-sun')).not.toBeNull()
  })

  it('pressing adds or removes the dark class and stores the choice', async () => {
    fakeSystem(false)
    render(<AppHeader />)
    expect(isDark()).toBe(false)
    await userEvent.click(screen.getByRole('button', { name: 'Switch to dark theme' }))
    expect(isDark()).toBe(true)
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark')
    await userEvent.click(screen.getByRole('button', { name: 'Switch to light theme' }))
    expect(isDark()).toBe(false)
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('light')
  })
})

describe('starting theme and system changes (AC-23.54)', () => {
  it('starts in the stored theme even when the system says otherwise', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'dark')
    fakeSystem(false)
    render(<AppHeader />)
    expect(isDark()).toBe(true)
    expect(screen.getByRole('button', { name: 'Switch to light theme' })).toBeInTheDocument()
  })

  it('with nothing stored follows the system setting and its live changes', () => {
    const system = fakeSystem(true)
    render(<AppHeader />)
    expect(isDark()).toBe(true)
    system.set(false)
    expect(isDark()).toBe(false)
    expect(screen.getByRole('button', { name: 'Switch to dark theme' })).toBeInTheDocument()
    system.set(true)
    expect(isDark()).toBe(true)
  })

  it('a stored choice is not overridden by a system change', async () => {
    const system = fakeSystem(false)
    render(<AppHeader />)
    await userEvent.click(screen.getByRole('button', { name: 'Switch to dark theme' }))
    system.set(false)
    expect(isDark()).toBe(true)
  })

  it('works when the browser has no matchMedia at all', () => {
    const saved = window.matchMedia
    // @ts-expect-error: simulate an environment without matchMedia
    delete window.matchMedia
    render(<AppHeader />)
    expect(isDark()).toBe(false)
    window.matchMedia = saved
  })
})

describe('blocked storage (AC-23.55)', () => {
  it('starts with the system setting and still toggles when localStorage throws', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    fakeSystem(true)
    render(<AppHeader />)
    expect(isDark()).toBe(true)
    await userEvent.click(screen.getByRole('button', { name: 'Switch to light theme' }))
    expect(isDark()).toBe(false)
  })
})

describe('no-flash inline script in index.html (AC-23.56)', () => {
  const inline = [...indexHtml.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1])

  function run({ stored, systemDark, storageThrows = false }: { stored?: string; systemDark: boolean; storageThrows?: boolean }) {
    const classes = new Set<string>()
    const doc = {
      documentElement: {
        classList: {
          toggle: (name: string, force: boolean) => (force ? classes.add(name) : classes.delete(name)),
        },
      },
    }
    const win = {
      localStorage: {
        getItem: (key: string) => {
          if (storageThrows) throw new Error('blocked')
          return key === THEME_STORAGE_KEY ? (stored ?? null) : null
        },
      },
      matchMedia: (q: string) => ({ matches: q === '(prefers-color-scheme: dark)' && systemDark }),
    }
    new Function('window', 'document', inline[0])(win, doc)
    return classes.has('dark')
  }

  it('is present exactly once, before the app module', () => {
    expect(inline).toHaveLength(1)
    expect(indexHtml.indexOf('<script>')).toBeLessThan(indexHtml.indexOf('/src/main.tsx'))
  })

  it.each([
    [{ stored: 'dark', systemDark: false }, true],
    [{ stored: 'light', systemDark: true }, false],
    [{ systemDark: true }, true],
    [{ systemDark: false }, false],
    [{ stored: 'purple', systemDark: true }, true],
    [{ stored: 'dark', systemDark: false, storageThrows: true }, false],
    [{ systemDark: true, storageThrows: true }, true],
  ])('%o gives dark = %s', (input, expected) => {
    expect(run(input)).toBe(expected)
  })
})
