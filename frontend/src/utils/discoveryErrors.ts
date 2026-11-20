/**
 * The one table that turns API failures into UI effects (spec 23 §3.11, §11.5; AC-23.42,
 * AC-23.68, AC-23.69, AC-23.72).
 * Why: every write can fail in the same dozen ways; deciding here once keeps the page, the picker
 * and Home consistent (lock vs banner vs reload, and 409 `map_incomplete` is not an error at all).
 * Rules: texts are fixed sentences or the server's own message; they never contain the expert's
 * text or the visitor key. Must not dispatch or render anything itself.
 * Part 2: the call decides the effect. An upload refusal goes to the Documents panel (`documents`),
 * never the banner, and 409 `document_limit` is not the `conflict` reload; a 404 on remove reloads.
 */
import { ApiError } from '../services/api'
import { documentSentence, type DocumentLimits } from './documentLimits'

export type ErrorContext = 'boot' | 'turn' | 'action' | 'picker' | 'finish' | 'list' | 'upload' | 'removeDocument' | 'proposals'

export type ErrorEffect =
  | { kind: 'lock'; message: string }
  | { kind: 'banner'; message: string }
  | { kind: 'init_failed'; message: string }
  | { kind: 'finish_blocked'; reason: string }
  | { kind: 'reload'; message: string }
  | { kind: 'picker'; message: string }
  | { kind: 'documents'; message: string }

export const ERROR_TEXT = {
  closed: 'This session is closed.',
  notFound: 'This session could not be found.',
  conflict: 'This session changed in another tab. It has been reloaded; please try again.',
  unknownCluster: 'That cluster is no longer available. Please pick another.',
  invalid: 'That could not be saved. Please check what you entered.',
  rateLimited: 'Too many requests. Please wait a moment and try again.',
  budget: 'The tool has reached its limit for today. Please try again tomorrow.',
  unavailable: 'The assistant is not available right now. Please try again later.',
  key: 'Your browser key is missing or damaged. Reload the page.',
  network: 'Could not reach the server. Check your connection and try again.',
  fallback: 'Something went wrong. Please try again.',
  documentRemoved: 'That document was already removed.',
} as const

const DOCUMENT_CODES = ['document_limit', 'document_too_large', 'document_type', 'document_unreadable', 'unsafe_input'] as const

/** The panel sentence for a refused upload (spec 23 §11.5): the server's when it sent one. */
function uploadSentence(error: unknown, limits: DocumentLimits | null): string {
  if (error instanceof ApiError) {
    const code = error.code === 'http_413' ? 'document_too_large' : error.code
    const known = (DOCUMENT_CODES as readonly string[]).includes(code)
    if (known) {
      return error.message.trim() && code === error.code ? error.message : documentSentence(code as (typeof DOCUMENT_CODES)[number], limits)
    }
    if (code === 'invalid_value') return documentSentence('invalid_value', limits)
  }
  return errorText(error)
}

/** The sentence for an error, ignoring where it happened (for lists, Home, notices). */
export function errorText(error: unknown): string {
  if (!(error instanceof ApiError)) return ERROR_TEXT.fallback
  switch (error.code) {
    case 'session_closed':
      return ERROR_TEXT.closed
    case 'not_found':
      return ERROR_TEXT.notFound
    case 'conflict':
      return ERROR_TEXT.conflict
    case 'unknown_cluster':
      return ERROR_TEXT.unknownCluster
    case 'rate_limited':
      return ERROR_TEXT.rateLimited
    case 'budget_exhausted':
      return ERROR_TEXT.budget
    case 'model_unavailable':
      return ERROR_TEXT.unavailable
    case 'visitor_key_required':
      return ERROR_TEXT.key
    case 'network':
      return ERROR_TEXT.network
  }
  if (error.status === 422) return ERROR_TEXT.invalid
  return error.message.trim() && !error.code.startsWith('http_') ? error.message : ERROR_TEXT.fallback
}

export function errorEffect(error: unknown, context: ErrorContext, limits: DocumentLimits | null = null): ErrorEffect {
  if (error instanceof ApiError) {
    if (error.code === 'session_closed') return { kind: 'lock', message: ERROR_TEXT.closed }
    if (context === 'removeDocument' && error.code === 'not_found') return { kind: 'reload', message: ERROR_TEXT.documentRemoved }
  }
  if (context === 'upload' && !(error instanceof ApiError && error.code === 'conflict')) {
    return { kind: 'documents', message: uploadSentence(error, limits) }
  }
  if (error instanceof ApiError) {
    if (error.code === 'map_incomplete') return { kind: 'finish_blocked', reason: error.reason ?? 'below_gate' }
    if (error.code === 'conflict' && context !== 'boot') return { kind: 'reload', message: ERROR_TEXT.conflict }
    if (error.code === 'unknown_cluster') return { kind: 'picker', message: ERROR_TEXT.unknownCluster }
    if (error.code === 'unsafe_input') return { kind: 'banner', message: error.message || ERROR_TEXT.fallback }
  }
  const message = errorText(error)
  return context === 'boot' ? { kind: 'init_failed', message } : { kind: 'banner', message }
}
