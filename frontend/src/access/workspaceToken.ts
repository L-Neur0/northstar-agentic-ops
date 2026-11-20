/**
 * The workspace token of this browser tab (spec 23 §19.2 rules 3, 6–8; AC-23.106, AC-23.108,
 * AC-23.110, AC-23.114).
 * Why: a specialist logs in once per tab with the access code and a name; the token the server
 * returns is kept for the tab only, so closing the tab ends the workspace session.
 * Rules: stored as JSON under `pd_workspace` in `sessionStorage` (never `localStorage`, never the
 * code); read back only when it parses, has role `specialist` and has not expired, otherwise it is
 * removed; when storage throws, the token lives in memory for this tab.
 * Must not: touch the expert's visitor key, log the token, or put it in a URL.
 */
import type { WorkspaceLogin } from '../types/workspace'

export const WORKSPACE_TOKEN_KEY = 'pd_workspace'

let memory: WorkspaceLogin | null = null

function valid(value: unknown, now: number): value is WorkspaceLogin {
  if (typeof value !== 'object' || value === null) return false
  const v = value as Record<string, unknown>
  return (
    typeof v.token === 'string' &&
    v.token.length > 0 &&
    v.role === 'specialist' &&
    typeof v.name === 'string' &&
    typeof v.expiresAt === 'string' &&
    new Date(v.expiresAt).getTime() > now
  )
}

export function storeWorkspaceToken(login: WorkspaceLogin): void {
  const value: WorkspaceLogin = { token: login.token, role: login.role, name: login.name, expiresAt: login.expiresAt }
  memory = value
  try {
    sessionStorage.setItem(WORKSPACE_TOKEN_KEY, JSON.stringify(value))
  } catch {
    /* storage blocked: the memory copy serves this tab */
  }
}

export function clearWorkspaceToken(): void {
  memory = null
  try {
    sessionStorage.removeItem(WORKSPACE_TOKEN_KEY)
  } catch {
    /* storage blocked: nothing stored */
  }
}

/** The stored specialist token, or null (an invalid or expired one is removed). */
export function readWorkspaceToken(now: number = Date.now()): WorkspaceLogin | null {
  let raw: string | null
  try {
    raw = sessionStorage.getItem(WORKSPACE_TOKEN_KEY)
  } catch {
    raw = memory === null ? null : JSON.stringify(memory) // storage blocked: the memory copy
  }
  if (raw === null) return null
  let stored: unknown = null
  try {
    stored = JSON.parse(raw)
  } catch {
    stored = null
  }
  if (valid(stored, now)) return stored
  clearWorkspaceToken()
  return null
}
