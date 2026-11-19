/**
 * Tabs following the WAI-ARIA tabs pattern (spec 23 §3.8.9; AC-23.33).
 * Why: the Steps section shows one tab per step; keyboard users move with the arrow keys, Home and
 * End, and only the selected tab is in the Tab order (roving `tabindex`).
 * Rules: the strip scrolls horizontally and keeps the selected tab in view. Selection is owned by
 * the caller (`selected`, `onSelect`); this component holds no state.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57).
 */
import { useEffect, useRef, type KeyboardEvent, type ReactNode } from 'react'

export interface TabItem {
  id: string
  label: ReactNode
  title?: string
}

export function Tabs({
  items,
  selected,
  onSelect,
  label,
  idPrefix,
}: {
  items: TabItem[]
  selected: number
  onSelect: (index: number) => void
  label: string
  idPrefix: string
}) {
  const refs = useRef<Array<HTMLButtonElement | null>>([])

  useEffect(() => {
    refs.current[selected]?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
  }, [selected, items.length])

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const last = items.length - 1
    const next =
      e.key === 'ArrowRight' ? (selected >= last ? 0 : selected + 1)
      : e.key === 'ArrowLeft' ? (selected <= 0 ? last : selected - 1)
      : e.key === 'Home' ? 0
      : e.key === 'End' ? last
      : null
    if (next === null) return
    e.preventDefault()
    onSelect(next)
    refs.current[next]?.focus()
  }

  return (
    <div role="tablist" aria-label={label} onKeyDown={onKeyDown} className="flex gap-1 overflow-x-auto border-b border-line">
      {items.map((item, i) => {
        const isSelected = i === selected
        return (
          <button
            key={item.id}
            ref={(el) => {
              refs.current[i] = el
            }}
            type="button"
            role="tab"
            id={`${idPrefix}-tab-${i}`}
            aria-selected={isSelected}
            aria-controls={`${idPrefix}-panel`}
            tabIndex={isSelected ? 0 : -1}
            title={item.title}
            onClick={() => onSelect(i)}
            className={`-mb-px shrink-0 whitespace-nowrap border-b-2 px-2.5 py-1.5 text-xs font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary ${
              isSelected ? 'border-primary text-link' : 'border-transparent text-muted hover:text-fg'
            }`}
          >
            {item.label}
          </button>
        )
      })}
    </div>
  )
}
