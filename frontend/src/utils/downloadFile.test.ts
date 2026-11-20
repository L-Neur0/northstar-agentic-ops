/**
 * Tests for `saveBlob` (spec 23 §11.13; AC-23.99).
 * Why: the PDF download goes through an object URL and a temporary link; both must be cleaned up
 * so no blob URL outlives the click.
 * What: stubs `URL.createObjectURL` / `revokeObjectURL` and watches the link's click.
 * Must not: start a real download.
 */
import { saveBlob } from './downloadFile'

afterEach(() => vi.restoreAllMocks())

it('clicks a temporary link with the file name, then removes it and revokes the URL (AC-23.99)', () => {
  const create = vi.fn(() => 'blob:fake-url')
  const revoke = vi.fn()
  Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke })
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  const blob = new Blob(['%PDF'], { type: 'application/pdf' })
  saveBlob(blob, 'discovery-report-monthly-cost-review.pdf')
  expect(create).toHaveBeenCalledWith(blob)
  const clicked = click.mock.contexts[0] as HTMLAnchorElement
  expect(clicked.download).toBe('discovery-report-monthly-cost-review.pdf')
  expect(clicked.href).toBe('blob:fake-url')
  expect(document.body.contains(clicked)).toBe(false)
  expect(revoke).toHaveBeenCalledWith('blob:fake-url')
})
