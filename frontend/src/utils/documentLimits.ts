/**
 * Document limits on the client: the helper line, the file input `accept` list, the pre-checks and
 * the list's count words (spec 23 §11.3, §11.6; spec 17 §3.2, §3.12; AC-23.61, AC-23.63, AC-23.70).
 * Why: an expert should learn that a file is too large or of the wrong type before waiting for an
 * upload, but the limits are company configuration, so every value here comes from
 * `GET /api/config` and every sentence is the server's (spec 17 §3.12).
 * Rules: pre-checks run in the server's order (count, size, extension); an empty file counts as
 * unreadable. Must not: type a limit, read the file's content, or replace the server's checks
 * (the server checks everything again).
 */
import { DOCUMENT_ERROR_SENTENCES, DOCUMENT_KIND_WORDS, type DocumentOut, type PublicConfig } from '../types/process-discovery'

export type DocumentLimits = PublicConfig['documents']

const MB = 1_048_576
const NAME_MAX = 60

/** The word for a kind or extension ("docx" → "Word"); an unknown one upper case. */
export function kindWord(kind: string): string {
  return DOCUMENT_KIND_WORDS[kind.toLowerCase()] ?? kind.toUpperCase()
}

const mb = (n: number) => String(Number(n.toFixed(2)))

const IMAGE_EXTENSIONS = ['png', 'jpg', 'jpeg']

/** "PDF, Word, … or BPMN · up to 10 MB · up to 5 files". */
export function helperLine(limits: DocumentLimits): string {
  const words = [...new Set(limits.allowedTypes.map(kindWord))]
  const types = words.length > 1 ? `${words.slice(0, -1).join(', ')} or ${words[words.length - 1]}` : (words[0] ?? '')
  return `${types} · up to ${mb(limits.maxFileMb)} MB · up to ${limits.maxFiles} files`
}

export function acceptOf(limits: DocumentLimits): string {
  return limits.allowedTypes.map((t) => `.${t}`).join(',')
}

/** A spec 17 §3.12 refusal sentence with `<max>` filled from the config (or left generic). */
export function documentSentence(code: keyof typeof DOCUMENT_ERROR_SENTENCES, limits: DocumentLimits | null): string {
  const max = code === 'document_limit' ? limits?.maxFiles : code === 'document_too_large' ? limits?.maxFileMb : undefined
  const text: string = DOCUMENT_ERROR_SENTENCES[code]
  if (max === undefined) {
    return code === 'document_limit'
      ? 'You have reached the document limit. Remove one to add another.'
      : code === 'document_too_large'
        ? 'This file is too large.'
        : text
  }
  return text.replace('<max>', code === 'document_too_large' ? mb(max) : String(max))
}

/** "This file type can't be read. Use <the allowed kinds>." (spec 17 §3.19 item 8), from the config. */
export function typeSentence(limits: DocumentLimits): string {
  const words = [...new Set(limits.allowedTypes.map(kindWord))]
  const listed = words.length > 1 ? `${words.slice(0, -1).join(', ')} or ${words[words.length - 1]}` : (words[0] ?? '')
  return `This file type can't be read. Use ${listed}.`
}

/** The refusal sentence for a file, or null when it may be sent. */
export function precheck(file: File, count: number, limits: DocumentLimits): string | null {
  if (count >= limits.maxFiles) return documentSentence('document_limit', limits)
  const ext = file.name.includes('.') ? file.name.split('.').pop()!.toLowerCase() : ''
  const image = IMAGE_EXTENSIONS.includes(ext) && limits.allowedTypes.includes(ext)
  const maxMb = image ? limits.maxImageMb : limits.maxFileMb
  if (file.size > maxMb * MB) return image ? `This image is larger than ${mb(maxMb)} MB.` : documentSentence('document_too_large', limits)
  if (file.size === 0) return documentSentence('document_unreadable', limits)
  if (!limits.allowedTypes.includes(ext)) return typeSentence(limits)
  return null
}

/** A file name cut to 60 characters with "…". */
export function cutName(name: string): string {
  return name.length > NAME_MAX ? `${name.slice(0, NAME_MAX - 1)}…` : name
}

/** The muted count line of one document (spec 23 §11.6.1). */
export function countText(doc: DocumentOut): string {
  if (doc.outcome === 'failed') return 'could not be read'
  if (doc.proposals === 0) return 'nothing new for the form'
  const noun = doc.proposals === 1 ? 'proposal' : 'proposals'
  return doc.pending > 0 ? `${doc.proposals} ${noun} · ${doc.pending} waiting for you` : `${doc.proposals} ${noun} · all settled`
}
