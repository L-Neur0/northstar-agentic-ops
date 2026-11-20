/**
 * Saves a fetched file under a given name (spec 23 §11.13; AC-23.99).
 * Why: the report PDF must be fetched with the visitor key (a plain link cannot send it), so the
 * browser's download is started from the blob through a temporary `<a download>`.
 * Rules: the object URL lives only for the click and is revoked at once; the link is removed.
 * Must not: read or change the file, or keep a reference to it.
 */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.rel = 'noopener'
  link.style.display = 'none'
  document.body.appendChild(link)
  try {
    link.click()
  } finally {
    link.remove()
    URL.revokeObjectURL(url)
  }
}
