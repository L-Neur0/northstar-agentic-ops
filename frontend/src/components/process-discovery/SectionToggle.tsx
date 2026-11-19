/**
 * Header button of a collapsible panel section (spec 23 §3.8.2; AC-23.28).
 * Why: every section of "Your process" opens and closes the same way: a chevron, the title and a
 * `complete/total` count, with `aria-expanded` and `aria-controls` pointing at the body.
 * Rules: presentation only; the page owns the open / pinned map.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57).
 */
import { ChevronDown, ChevronRight } from 'lucide-react'

export function SectionToggle({
  title,
  count,
  collapsed,
  controls,
  onToggle,
}: {
  title: string
  count: string
  collapsed: boolean
  controls: string
  onToggle: () => void
}) {
  const Chevron = collapsed ? ChevronRight : ChevronDown
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={!collapsed}
      aria-controls={controls}
      className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-fg hover:bg-surface-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
    >
      <Chevron className="h-4 w-4 shrink-0 text-subtle" aria-hidden="true" />
      <span className="flex-1 text-sm font-semibold">{title}</span>
      <span className="text-xs text-subtle">{count}</span>
    </button>
  )
}
