/**
 * The workspace login card: access code and name (spec 23 §19.2; AC-23.107–23.110).
 * Why: the IT and transformation specialist opens the workspace with the team's access code and
 * a name that the server writes into its log next to what they open.
 * Rules: **Open workspace** is disabled while a field is blank or a login is in flight; a
 * specialist login is stored (the code never is) and handed to the page; an engineer login stores
 * nothing and says their screens are not ready; a wrong code clears and focuses the code field and
 * keeps the name. With `open` (open demo workspace, spec 23 §19.2 rule 10, AC-23.143, amended
 * 2026-11-20) there is no code field: the name alone logs in and a line says the workspace is
 * open and delete is off. Must not: store or log the code, or touch the expert's visitor key.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.141).
 */
import { useId, useRef, useState, type FormEvent } from 'react'
import { Button } from '../ui/Button'
import { useApi } from '../../services/apiContext'
import { ApiError } from '../../services/api'
import { storeWorkspaceToken } from '../../access/workspaceToken'
import { errorText, WORKSPACE_TEXT } from '../../utils/discoveryErrors'
import type { WorkspaceLogin as Login } from '../../types/workspace'

const INPUT =
  'mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary'

export const OPEN_WORKSPACE_LINE = 'Open demo workspace: anyone with the link can read sessions. Deleting is switched off.'

export function WorkspaceLogin({
  notice,
  onLoggedIn,
  open = false,
}: {
  notice?: string | null
  onLoggedIn: (login: Login) => void
  /** The server's `workspaceOpen` (`GET /api/config`): ask for the name only. */
  open?: boolean
}) {
  const api = useApi()
  const id = useId()
  const codeRef = useRef<HTMLInputElement>(null)
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const blank = (!open && !code.trim()) || !name.trim()

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (blank || busy) return
    setBusy(true)
    setError(null)
    try {
      const login = await api.workspaceLogin(open ? '' : code.trim(), name.trim())
      if (login.role !== 'specialist') {
        setError(WORKSPACE_TEXT.engineer)
        return
      }
      storeWorkspaceToken(login)
      onLoggedIn(login)
    } catch (err) {
      if (err instanceof ApiError && err.code === 'workspace_code_invalid') {
        setError(WORKSPACE_TEXT.codeInvalid)
        setCode('')
        codeRef.current?.focus()
      } else if (err instanceof ApiError && err.code === 'rate_limited' && err.message.trim()) {
        setError(err.message)
      } else {
        setError(errorText(err))
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex justify-center px-4 py-12">
      <form
        onSubmit={(e) => void submit(e)}
        aria-labelledby={`${id}-title`}
        className="w-full max-w-[400px] rounded-lg border border-line bg-surface p-6 shadow-sm"
      >
        <h2 id={`${id}-title`} className="text-xl font-semibold text-fg">
          Workspace
        </h2>
        <p className="mt-1 text-sm text-muted">For the IT and transformation team.</p>
        {open && <p className="mt-2 text-sm text-fg">{OPEN_WORKSPACE_LINE}</p>}
        {notice && (
          <p role="status" className="mt-4 rounded-md border border-warning/40 bg-warning-soft px-3 py-2 text-sm text-warning">
            {notice}
          </p>
        )}
        {!open && (
          <label className="mt-4 block text-sm font-medium text-fg">
            Access code
            <input
              ref={codeRef}
              type="password"
              autoComplete="off"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              className={INPUT}
            />
          </label>
        )}
        <label className={`${open ? 'mt-4' : 'mt-3'} block text-sm font-medium text-fg`}>
          Your name
          <input
            type="text"
            maxLength={40}
            value={name}
            aria-describedby={`${id}-name-help`}
            onChange={(e) => setName(e.target.value)}
            className={INPUT}
          />
        </label>
        <p id={`${id}-name-help`} className="mt-1 text-xs text-muted">
          Shown in the log next to what you open.
        </p>
        {error && (
          <p role="alert" className="mt-3 text-sm text-danger">
            {error}
          </p>
        )}
        <Button type="submit" variant="primary" className="mt-4 w-full" disabled={blank} loading={busy}>
          {busy ? 'Opening…' : 'Open workspace'}
        </Button>
      </form>
    </div>
  )
}
