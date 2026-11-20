/**
 * One case per row of the error table of spec 23 §3.11 (AC-23.42).
 * Why: every screen turns API failures into UI effects through `errorEffect`, so this table is
 * the single place where "lock", "banner", "reload" and "not an error" are decided.
 * Rules: error texts never contain the expert's message; 409 `map_incomplete` is not an error.
 */
import { ApiError } from '../services/api'
import { errorEffect } from './discoveryErrors'

const err = (status: number, code: string, message = 'Server sentence.', reason?: string) =>
  new ApiError(status, code, message, reason)

describe('errorEffect (AC-23.42)', () => {
  it('session_closed locks without a banner', () => {
    expect(errorEffect(err(400, 'session_closed'), 'turn')).toEqual({ kind: 'lock', message: 'This session is closed.' })
  })

  it('unsafe_input shows the server sentence in the banner', () => {
    expect(errorEffect(err(400, 'unsafe_input', 'That message cannot be processed.'), 'turn')).toEqual({
      kind: 'banner',
      message: 'That message cannot be processed.',
    })
  })

  it('not_found fails the boot, and is a banner elsewhere', () => {
    expect(errorEffect(err(404, 'not_found'), 'boot')).toEqual({ kind: 'init_failed', message: 'This session could not be found.' })
    expect(errorEffect(err(404, 'not_found'), 'action')).toEqual({ kind: 'banner', message: 'This session could not be found.' })
  })

  it('map_incomplete is not an error: it carries the reason', () => {
    expect(errorEffect(err(409, 'map_incomplete', 'x', 'roles_not_confirmed'), 'finish')).toEqual({
      kind: 'finish_blocked',
      reason: 'roles_not_confirmed',
    })
  })

  it('conflict reloads with its banner', () => {
    expect(errorEffect(err(409, 'conflict'), 'action')).toEqual({
      kind: 'reload',
      message: 'This session changed in another tab. It has been reloaded; please try again.',
    })
  })

  it('unknown_cluster stays inside the picker', () => {
    expect(errorEffect(err(422, 'unknown_cluster'), 'picker')).toEqual({
      kind: 'picker',
      message: 'That cluster is no longer available. Please pick another.',
    })
  })

  it.each([
    [422, 'invalid_value', 'That could not be saved. Please check what you entered.'],
    [429, 'rate_limited', 'Too many requests. Please wait a moment and try again.'],
    [429, 'budget_exhausted', 'The tool has reached its limit for today. Please try again tomorrow.'],
    [503, 'model_unavailable', 'The assistant is not available right now. Please try again later.'],
    [401, 'visitor_key_required', 'Your browser key is missing or damaged. Reload the page.'],
    [0, 'network', 'Could not reach the server. Check your connection and try again.'],
  ])('%i %s → banner', (status, code, text) => {
    expect(errorEffect(err(status, code), 'action')).toEqual({ kind: 'banner', message: text })
  })

  it('anything else shows the server message, else a fallback', () => {
    expect(errorEffect(err(500, 'internal', 'Boom happened.'), 'action')).toEqual({ kind: 'banner', message: 'Boom happened.' })
    expect(errorEffect(err(500, 'http_500', ''), 'action')).toEqual({ kind: 'banner', message: 'Something went wrong. Please try again.' })
    expect(errorEffect(new Error('x'), 'action')).toEqual({ kind: 'banner', message: 'Something went wrong. Please try again.' })
  })

  it('any other boot failure shows the init-failed view with its sentence', () => {
    expect(errorEffect(err(0, 'network'), 'boot')).toEqual({
      kind: 'init_failed',
      message: 'Could not reach the server. Check your connection and try again.',
    })
  })
})

describe('document calls (spec 23 §11.5; AC-23.68, AC-23.69, AC-23.72)', () => {
  const limits = { allowedTypes: ['pdf', 'docx'], maxFiles: 5, maxFileMb: 10, maxImageMb: 5 }

  it.each([
    [409, 'document_limit', 'You can add up to 5 documents. Remove one to add another.'],
    [413, 'document_too_large', 'This file is larger than 10 MB.'],
    [413, 'http_413', 'This file is larger than 10 MB.'],
    [415, 'document_type', "This file type can't be read. Use PDF, Word, Excel, CSV, text, Markdown or BPMN."],
    [422, 'document_unreadable', "I couldn't find any text in this file. If it is a scan, try the file it was made from."],
    [400, 'unsafe_input', "This document contains text that looks like instructions to the assistant, so I didn't read it."],
    [422, 'invalid_value', 'That file could not be sent. Please try again.'],
    [429, 'budget_exhausted', 'The tool has reached its limit for today. Please try again tomorrow.'],
    [0, 'network', 'Could not reach the server. Check your connection and try again.'],
  ])('upload %i %s → panel sentence, not a banner (AC-23.68)', (status, code, text) => {
    expect(errorEffect(err(status, code, code.startsWith('http_') ? 'HTTP 413' : ''), 'upload', limits)).toEqual({
      kind: 'documents',
      message: text,
    })
  })

  it('upload prefers the server sentence for a document code', () => {
    expect(errorEffect(err(409, 'document_limit', 'You can add up to 3 documents. Remove one to add another.'), 'upload')).toEqual({
      kind: 'documents',
      message: 'You can add up to 3 documents. Remove one to add another.',
    })
  })

  it('document_limit is not the conflict reload; conflict still reloads (AC-23.68, AC-23.69)', () => {
    expect(errorEffect(err(409, 'document_limit'), 'upload', limits).kind).toBe('documents')
    expect(errorEffect(err(409, 'conflict'), 'upload').kind).toBe('reload')
    expect(errorEffect(err(409, 'conflict'), 'proposals').kind).toBe('reload')
  })

  it('session_closed locks on upload, removal and proposals (AC-23.69)', () => {
    for (const call of ['upload', 'removeDocument', 'proposals'] as const) {
      expect(errorEffect(err(400, 'session_closed'), call).kind).toBe('lock')
    }
  })

  it('a 404 on remove reloads the session with its sentence (AC-23.72)', () => {
    expect(errorEffect(err(404, 'not_found'), 'removeDocument')).toEqual({ kind: 'reload', message: 'That document was already removed.' })
  })
})
