/**
 * Roles and systems review (spec 23 §3.8.11; AC-23.34, AC-23.35; F-10).
 * Why: the derived review. The lists are rolled up by the server from the
 * steps and stay read-only; confirming each is an explicit press because two *Finish* conditions
 * hang on it. Confirming an empty list could be a mis-click, so it asks a second time.
 * Rules: "roles" confirms roles, "tools" confirms systems (spec 15 route 6); both buttons are
 * disabled while any confirm is in flight or the session is not active; corrections go through
 * the chat. Status is shown in words, never by colour alone.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57).
 */
import { useRef, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { Button } from '../ui/Button'
import { Modal } from '../ui/Modal'
import type { ConfirmTarget } from '../../types/process-discovery'

interface Props {
  roles: string[]
  tools: string[]
  rolesConfirmed: boolean
  toolsConfirmed: boolean
  /** The confirm in flight, if any. */
  confirming: ConfirmTarget | null
  /** True when the session is closed or locked. */
  disabled: boolean
  onConfirm: (target: ConfirmTarget) => void
}

function Row({ label, noun, values, confirmed, busy, disabled, onPress }: {
  label: string
  noun: string
  values: string[]
  confirmed: boolean
  busy: boolean
  disabled: boolean
  onPress: () => void
}) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="text-sm font-medium text-fg">{label}</span>
        <span className={`text-xs ${confirmed ? 'text-success' : 'text-warning'}`}>{confirmed ? '✓ Confirmed' : 'Not confirmed yet'}</span>
      </div>
      {values.length === 0 ? (
        <p className="text-sm italic text-subtle">None yet</p>
      ) : (
        <ul className="flex flex-wrap gap-1" aria-label={label}>
          {values.map((v) => (
            <li key={v} className="rounded bg-surface-muted px-1.5 py-0.5 text-xs text-fg ring-1 ring-inset ring-line">
              {v}
            </li>
          ))}
        </ul>
      )}
      {!confirmed && (
        <Button size="sm" className="mt-1.5" onClick={onPress} disabled={disabled} loading={busy}>
          Confirm {noun}
        </Button>
      )}
    </div>
  )
}

export function DerivedReviewPanel({ roles, tools, rolesConfirmed, toolsConfirmed, confirming, disabled, onConfirm }: Props) {
  const [askEmpty, setAskEmpty] = useState<ConfirmTarget | null>(null)
  const cancelRef = useRef<HTMLButtonElement>(null)
  const off = disabled || confirming !== null
  const press = (target: ConfirmTarget, empty: boolean) => (empty ? setAskEmpty(target) : onConfirm(target))
  const noun = askEmpty === 'tools' ? 'systems' : 'roles'

  return (
    <div className="flex flex-col gap-3 px-3 pb-3">
      <Row label="Roles" noun="roles" values={roles} confirmed={rolesConfirmed} busy={confirming === 'roles'} disabled={off} onPress={() => press('roles', roles.length === 0)} />
      <Row label="Systems" noun="systems" values={tools} confirmed={toolsConfirmed} busy={confirming === 'tools'} disabled={off} onPress={() => press('tools', tools.length === 0)} />
      <p className="text-xs text-subtle">To correct an entry, say it in the chat.</p>
      {askEmpty && (
        <Modal
          role="alertdialog"
          size="sm"
          title={`Confirm that no ${noun} are involved?`}
          icon={<AlertTriangle className="h-5 w-5 text-warning" aria-hidden="true" />}
          description={`No ${noun} were named in your steps. Confirming records that this process involves none. Naming one later in the chat opens the confirmation again.`}
          onClose={() => setAskEmpty(null)}
          initialFocusRef={cancelRef}
          footer={
            <>
              <Button ref={cancelRef} onClick={() => setAskEmpty(null)}>
                Cancel
              </Button>
              <Button
                variant="primary"
                onClick={() => {
                  onConfirm(askEmpty)
                  setAskEmpty(null)
                }}
              >
                Yes, confirm
              </Button>
            </>
          }
        >
          {null}
        </Modal>
      )}
    </div>
  )
}
