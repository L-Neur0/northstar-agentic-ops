/**
 * The page title bar used on every page (spec 23 §3.1.2; AC-23.6).
 * Why: every screen shares one title row: a neutral icon, the `<h1>` title and an actions
 * slot on the right. This is that row in Tailwind: 56 px high, plain neutral template.
 * Rules: title is the product name ("AI Use Case Discovery Agent", renamed 2026-11-21) and no logo
 * or company branding (spec 23 §2 "Look"); under the `sm` breakpoint the short form shows so the
 * title fits a phone, while the heading's accessible name stays the full title. Must not
 * hold navigation logic; pages pass their own actions.
 * The light/dark theme toggle sits at the far right on every page (spec 23 §3.13.3; AC-23.52).
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57).
 */
import type { ReactNode } from 'react'
import { Search } from 'lucide-react'
import { ThemeToggle } from '../../theme/ThemeToggle'
import { PRODUCT_NAME, PRODUCT_SHORT_NAME } from '../../config/product'

export function AppHeader({
  title = PRODUCT_NAME,
  shortTitle = PRODUCT_SHORT_NAME,
  actions,
}: {
  title?: string
  shortTitle?: string
  actions?: ReactNode
}) {
  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line bg-surface px-4">
      <Search className="h-5 w-5 text-subtle" aria-hidden="true" />
      <h1 aria-label={title} className="min-w-0 flex-1 truncate text-lg font-semibold text-fg">
        <span aria-hidden="true" className="sm:hidden">
          {shortTitle}
        </span>
        <span aria-hidden="true" className="hidden sm:inline">
          {title}
        </span>
      </h1>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
      <ThemeToggle />
    </header>
  )
}
