/**
 * Theme choice, storage and application (spec 23 §3.13.1, §3.13.4, §3.13.5; AC-23.53 to AC-23.55).
 * Why: the app has a light and a dark theme; the expert's choice is remembered, and without a
 * choice the theme follows the system setting. These plain functions hold that logic so the hook
 * and the tests share it; the inline script in `index.html` repeats the same start rule.
 * Rules: only "light" and "dark" are valid stored values (anything else counts as no choice);
 * storage and `matchMedia` may be missing or throw, and then the system setting (or light) wins.
 * Must not: touch any element other than `<html>`, or store anything but `pd_theme`.
 */
export type Theme = 'light' | 'dark'

export const THEME_STORAGE_KEY = 'pd_theme'
export const DARK_QUERY = '(prefers-color-scheme: dark)'

/** The stored choice, or null when nothing valid is stored or storage is blocked. */
export function readStoredTheme(): Theme | null {
  try {
    const value = localStorage.getItem(THEME_STORAGE_KEY)
    return value === 'light' || value === 'dark' ? value : null
  } catch {
    return null
  }
}

/** Remembers the choice; blocked storage is ignored (the choice lasts for this tab only). */
export function storeTheme(theme: Theme): void {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme)
  } catch {
    /* storage blocked: the hook keeps the choice in memory */
  }
}

/** The system dark-mode query, or null when the browser has no `matchMedia`. */
export function darkQuery(): MediaQueryList | null {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' ? window.matchMedia(DARK_QUERY) : null
}

/** Sets or removes the `dark` class on `<html>`. */
export function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle('dark', theme === 'dark')
}
