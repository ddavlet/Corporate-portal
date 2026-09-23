/**
 * Saves a downloaded file through a hidden link (as RequestDetailModal does): window.open after an await is
 * blocked by popup rules. The object URL is released a minute later, after the browser has read it.
 */
export function saveFile(file: { blob: Blob; filename: string }): void {
  const url = URL.createObjectURL(file.blob)
  const link = document.createElement('a')
  link.href = url
  link.download = file.filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
}
