/**
 * The page title bar used on every page (spec 23 §3.1.2; AC-23.6).
 * Why: every screen shares one title row: a neutral icon, the `<h1>` title and an actions
 * slot on the right. This is that row in Tailwind: 56 px high, plain neutral template.
 * Rules: title "Process Discovery" and no logo or company branding (spec 23 §2 "Look"). Must not
 * hold navigation logic; pages pass their own actions.
 * The light/dark theme toggle sits at the far right on every page (spec 23 §3.13.3; AC-23.52).
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57).
 */
import type { ReactNode } from 'react'
import { Search } from 'lucide-react'
import { ThemeToggle } from '../../theme/ThemeToggle'

export function AppHeader({ title = 'Process Discovery', actions }: { title?: string; actions?: ReactNode }) {
  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line bg-surface px-4">
      <Search className="h-5 w-5 text-subtle" aria-hidden="true" />
      <h1 className="flex-1 truncate text-lg font-semibold text-fg">{title}</h1>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
      <ThemeToggle />
    </header>
  )
}
