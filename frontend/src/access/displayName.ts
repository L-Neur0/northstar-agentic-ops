/**
 * The expert's optional first name (spec 23 §3.3.6; AC-23.10; behaviour 9 of spec 23 §5).
 * Why: the agent greets the expert by first name; the name is sent as `displayName` on every
 * session create, and it must be read synchronously so the very first create carries it.
 * Rules: at most 40 characters, kept in `localStorage` under `discovery_display_name`; empty means
 * "omit". Storage failures are swallowed (the name is a nicety, never required).
 */
export const DISPLAY_NAME_KEY = 'discovery_display_name'
export const DISPLAY_NAME_MAX = 40

export function readDisplayName(): string {
  try {
    return (localStorage.getItem(DISPLAY_NAME_KEY) ?? '').slice(0, DISPLAY_NAME_MAX)
  } catch {
    return ''
  }
}

export function writeDisplayName(name: string): void {
  try {
    const value = name.slice(0, DISPLAY_NAME_MAX)
    if (value.trim()) localStorage.setItem(DISPLAY_NAME_KEY, value)
    else localStorage.removeItem(DISPLAY_NAME_KEY)
  } catch {
    /* storage blocked: the name is not kept */
  }
}

/** The name to send on create, or undefined when empty. */
export function displayNameForCreate(): string | undefined {
  const name = readDisplayName().trim()
  return name ? name : undefined
}
