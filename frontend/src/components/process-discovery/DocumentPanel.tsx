/**
 * The Documents section of "Your process": add a document, see the upload, its result sentence,
 * the list of documents with their counts, and remove one (spec 23 §11.2–§11.6; AC-23.61,
 * AC-23.64, AC-23.65, AC-23.67, AC-23.70, AC-23.71, AC-23.74).
 * Why: starting from a procedure or a process map saves interview time, but the expert must see
 * what was read (as counts and the server's sentence) and stay in control of every document.
 * Rules: the limits and the helper line come from the config (none typed here); the counts, the
 * sentences and the list come from the server; refusals show inside the panel (`role="alert"`),
 * results as a dismissible status. On a finished or ended session the list stays, read-only.
 * Must not: show a document's text, size or character count, count proposals itself, or close the
 * section by itself.
 * Colours are theme tokens only, never raw palette classes (spec 23 §3.13.2; AC-23.57, AC-23.102).
 */
import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, Info, X } from 'lucide-react'
import { Button } from '../ui/Button'
import { Modal } from '../ui/Modal'
import { ProgressBar } from '../ui/ProgressBar'
import { Spinner } from '../ui/Spinner'
import { SectionToggle } from './SectionToggle'
import { FileDrop } from './FileDrop'
import { countText, cutName, helperLine, kindWord, type DocumentLimits } from '../../utils/documentLimits'
import type { Uploading } from '../../hooks/discoveryReducer'
import type { DocumentOut } from '../../types/process-discovery'

const SLOW_READ_MS = 20_000

function Reading({ name }: { name: string }) {
  const [slow, setSlow] = useState(false)
  useEffect(() => {
    const t = setTimeout(() => setSlow(true), SLOW_READ_MS)
    return () => clearTimeout(t)
  }, [])
  return (
    <div role="status" className="flex items-center gap-2 text-sm text-muted">
      <Spinner size="sm" />
      <span>{slow ? 'Still reading. A long document can take up to a minute.' : `Reading ${cutName(name)}…`}</span>
    </div>
  )
}

function Note({ tone, text, onClose }: { tone: 'info' | 'error'; text: string; onClose: () => void }) {
  const error = tone === 'error'
  return (
    <div
      role={error ? 'alert' : 'status'}
      className={`flex items-start gap-2 rounded-md px-2.5 py-2 text-sm ${error ? 'bg-danger-soft text-danger' : 'bg-primary-soft text-link'}`}
    >
      {error ? <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" /> : <Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />}
      <p className="flex-1">{text}</p>
      <button type="button" onClick={onClose} aria-label="Dismiss" className="rounded p-0.5 hover:bg-fg/5">
        <X className="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  )
}

interface Props {
  documents: DocumentOut[]
  /** Active and not locked: adding and removing are offered. */
  editable: boolean
  /** Another write or a turn is in flight. */
  busy: boolean
  limits: DocumentLimits | null
  uploading: Uploading | null
  removingId: string | null
  notice: string | null
  error: string | null
  collapsed: boolean
  onToggle: () => void
  onOpenPicker: () => void
  onFile: (file: File) => void
  onRemove: (docId: string) => void
  onDismissNotice: () => void
  onDismissError: () => void
}

export function DocumentPanel({
  documents,
  editable,
  busy,
  limits,
  uploading,
  removingId,
  notice,
  error,
  collapsed,
  onToggle,
  onOpenPicker,
  onFile,
  onRemove,
  onDismissNotice,
  onDismissError,
}: Props) {
  const [dropNote, setDropNote] = useState<string | null>(null)
  const [confirmRemove, setConfirmRemove] = useState<DocumentOut | null>(null)
  const cancelRef = useRef<HTMLButtonElement>(null)

  const onFiles = (files: File[]) => {
    setDropNote(files.length > 1 ? `One file at a time: I took ${files[0].name}.` : null)
    onFile(files[0])
  }

  return (
    <section className="overflow-hidden rounded-lg border border-line bg-surface">
      <SectionToggle
        title="Documents"
        count={`${documents.length}/${limits?.maxFiles ?? '–'}`}
        collapsed={collapsed}
        controls="section-body-documents"
        onToggle={onToggle}
      />
      <div id="section-body-documents" hidden={collapsed} className="flex flex-col gap-2 px-3 pb-3">
        {editable && (
          <>
            <FileDrop
              onOpen={() => {
                setDropNote(null)
                onOpenPicker()
              }}
              onFiles={onFiles}
              disabled={busy}
            />
            {limits && <p className="text-xs text-subtle">{helperLine(limits)}</p>}
          </>
        )}

        {uploading &&
          (uploading.stage === 'sending' ? (
            <div className="flex flex-col gap-1 text-sm text-muted">
              <span>Uploading {cutName(uploading.name)}</span>
              <ProgressBar value={uploading.percent ?? 0} label="Upload progress" colorClass="bg-primary" />
            </div>
          ) : (
            <Reading name={uploading.name} />
          ))}

        {dropNote && <p className="text-xs text-muted">{dropNote}</p>}
        {notice && <Note tone="info" text={notice} onClose={onDismissNotice} />}
        {error && <Note tone="error" text={error} onClose={onDismissError} />}

        {documents.length === 0 ? (
          <p className="text-sm italic text-subtle">No documents yet.</p>
        ) : (
          <ul aria-label="Your documents" className="flex flex-col">
            {documents.map((doc) => (
              <li key={doc.id} className="flex items-start gap-2 border-t border-line py-1.5 first:border-t-0">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-fg" title={doc.name}>
                    {doc.name}
                  </p>
                  <p className="text-xs text-muted">
                    {[kindWord(doc.kind), doc.truncated ? 'read in part' : null, countText(doc)].filter(Boolean).join(' · ')}
                  </p>
                </div>
                {editable &&
                  (removingId === doc.id ? (
                    <span role="status" className="text-xs text-muted">
                      Removing…
                    </span>
                  ) : (
                    <Button size="sm" aria-label={`Remove ${doc.name}`} disabled={busy} onClick={() => setConfirmRemove(doc)}>
                      Remove
                    </Button>
                  ))}
              </li>
            ))}
          </ul>
        )}
      </div>

      {confirmRemove && (
        <Modal
          role="alertdialog"
          size="sm"
          title="Remove this document?"
          onClose={() => setConfirmRemove(null)}
          initialFocusRef={cancelRef}
          description={
            <>
              Values you already confirmed from it stay.
              {confirmRemove.pending > 0 && ` Its ${confirmRemove.pending} unconfirmed proposals are removed.`}
            </>
          }
          footer={
            <>
              <Button ref={cancelRef} onClick={() => setConfirmRemove(null)}>
                Cancel
              </Button>
              <Button
                variant="danger"
                onClick={() => {
                  const id = confirmRemove.id
                  setConfirmRemove(null)
                  onRemove(id)
                }}
              >
                Remove
              </Button>
            </>
          }
        >
          {null}
        </Modal>
      )}
    </section>
  )
}
