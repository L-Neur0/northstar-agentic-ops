/**
 * The header button that switches between the light and the dark theme (spec 23 §3.13.3; AC-23.52,
 * AC-23.53).
 * Why: every page offers the same one-press switch at the right of the header.
 * What: shows a moon in light mode ("Switch to dark theme") and a sun in dark mode ("Switch to
 * light theme"); `aria-label` and `title` say what a press does, `aria-pressed` is true in dark mode.
 * Must not: hold theme logic of its own; the `useTheme` hook owns state, storage and the class.
 */
import { Moon, Sun } from 'lucide-react'
import { useTheme } from './useTheme'

export function ThemeToggle() {
  const { theme, toggle } = useTheme()
  const dark = theme === 'dark'
  const label = dark ? 'Switch to light theme' : 'Switch to dark theme'
  const Icon = dark ? Sun : Moon
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={label}
      title={label}
      aria-pressed={dark}
      className="rounded-md p-1.5 text-muted hover:bg-surface-muted hover:text-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
    >
      <Icon className="h-5 w-5" aria-hidden="true" />
    </button>
  )
}
