/**
 * React hook for the current theme and its toggle (spec 23 §3.13.3, §3.13.4; AC-23.53 to AC-23.55).
 * Why: the header toggle needs the theme in effect and a way to flip it, and the page must follow
 * the system setting live while the expert has made no choice.
 * What: keeps the stored choice and the system answer in state, listens to the system query,
 * applies the result to `<html>` and stores a new choice on toggle (in memory if storage is blocked).
 * Must not: let a system change override a stored choice, or keep a listener after unmount.
 */
import { useCallback, useEffect, useState } from 'react'
import { applyTheme, darkQuery, readStoredTheme, storeTheme, type Theme } from './theme'

export function useTheme(): { theme: Theme; toggle: () => void } {
  const [chosen, setChosen] = useState<Theme | null>(readStoredTheme)
  const [systemDark, setSystemDark] = useState(() => darkQuery()?.matches ?? false)

  useEffect(() => {
    const query = darkQuery()
    if (!query) return
    const onChange = (e: { matches: boolean }) => setSystemDark(e.matches)
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])

  const theme: Theme = chosen ?? (systemDark ? 'dark' : 'light')

  useEffect(() => applyTheme(theme), [theme])

  const toggle = useCallback(() => {
    const next: Theme = theme === 'dark' ? 'light' : 'dark'
    storeTheme(next)
    setChosen(next)
  }, [theme])

  return { theme, toggle }
}
