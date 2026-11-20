/**
 * Tests for the document limits helper (spec 23 §11.3; AC-23.61, AC-23.63).
 * Why: the helper line, the `accept` list and the pre-checks are built from `GET /api/config`, and
 * the pre-checks must run in the server's order and say the server's sentences, so a refused file
 * never costs a call.
 * What: helper line and `accept` from the recorded config sample; each pre-check in order.
 * Must not: type a limit of its own; the limits come from the config sample.
 */
import config from '../test/fixtures/api/config.json'
import { acceptOf, cutName, helperLine, kindWord, precheck } from './documentLimits'

const limits = config.documents
const file = (name: string, size: number) => new File([new Uint8Array(size)], name)

describe('helper line and accept (AC-23.61)', () => {
  it('lists the type words once each, then MB and files', () => {
    expect(helperLine(limits)).toBe(
      'PDF, Word, Excel, PowerPoint, CSV, text, Markdown, e-mail (.eml), BPMN, PNG or JPG · up to 10 MB · up to 10 files',
    )
  })

  it('accept lists the configured extensions with dots', () => {
    expect(acceptOf(limits)).toBe('.pdf,.docx,.xlsx,.pptx,.csv,.txt,.md,.eml,.bpmn,.xml,.png,.jpg,.jpeg')
  })

  it('an unknown kind is shown upper case', () => {
    expect(kindWord('docx')).toBe('Word')
    expect(kindWord('odt')).toBe('ODT')
  })

  it('cuts a long name to 60 characters with an ellipsis', () => {
    expect(cutName('a'.repeat(80))).toBe(`${'a'.repeat(59)}…`)
    expect(cutName('short.pdf')).toBe('short.pdf')
  })
})

describe('pre-checks in the server order (AC-23.63)', () => {
  it('count first, even for a file that is also too large', () => {
    expect(precheck(file('x.exe', 11 * 1_048_576), 10, limits)).toBe('You can add up to 10 documents. Remove one to add another.')
  })

  it('size: over the limit, and an empty file counts as unreadable', () => {
    expect(precheck(file('big.pdf', 10 * 1_048_576 + 1), 0, limits)).toBe('This file is larger than 10 MB.')
    expect(precheck(file('empty.pdf', 0), 0, limits)).toBe(
      "I couldn't find any text in this file. If it is a scan, try the file it was made from.",
    )
  })

  it('extension last; the sentence lists the configured kinds (spec 17 §3.19 item 8)', () => {
    expect(precheck(file('mail.msg', 10), 0, limits)).toBe(
      "This file type can't be read. Use PDF, Word, Excel, PowerPoint, CSV, text, Markdown, e-mail (.eml), BPMN, PNG or JPG.",
    )
  })

  it('an image has its own size limit (maxImageMb)', () => {
    expect(precheck(file('shot.png', 5 * 1_048_576 + 1), 0, limits)).toBe('This image is larger than 5 MB.')
    expect(precheck(file('shot.jpg', 5 * 1_048_576), 0, limits)).toBeNull()
  })

  it('a good file passes', () => {
    expect(precheck(file('Procedure.DOCX', 10), 4, limits)).toBeNull()
  })
})
