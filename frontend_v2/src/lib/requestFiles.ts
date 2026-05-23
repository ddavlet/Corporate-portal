import type { RequestAttachment } from './api'

export type RequestFileRow = { key: string; url: string; label: string }

export type RequestFilesSource = {
  file_link?: string | null
  attachments?: RequestAttachment[] | null
}

/** Ключ файла для сравнения: storage path из ?path= или нормализованный URL/путь. */
export function normalizeRequestFileStorageKey(urlOrPath: string): string {
  const trimmed = urlOrPath.trim()
  if (!trimmed) return ''

  try {
    const queryStart = trimmed.indexOf('?')
    if (queryStart >= 0) {
      const search = trimmed.slice(queryStart + 1)
      const pathParam = new URLSearchParams(search).get('path')
      if (pathParam) {
        return decodeURIComponent(pathParam).replace(/\\/g, '/').toLowerCase()
      }
    }
    if (trimmed.startsWith('http://') || trimmed.startsWith('https://')) {
      const u = new URL(trimmed)
      const pathParam = u.searchParams.get('path')
      if (pathParam) {
        return decodeURIComponent(pathParam).replace(/\\/g, '/').toLowerCase()
      }
      return `${u.pathname}${u.search}`.toLowerCase()
    }
  } catch {
    // fall through
  }

  return trimmed.replace(/\\/g, '/').toLowerCase()
}

function formatAttachmentSize(sizeBytes?: number): string {
  const size = Number(sizeBytes || 0)
  if (!Number.isFinite(size) || size <= 0) return '-'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

function labelFromStorageKey(storageKey: string): string {
  const base = storageKey.split('/').filter(Boolean).pop()
  return base || 'Файл'
}

/**
 * Единый список файлов заявки: все attachments + file_link, если это не дубликат.
 */
export function buildRequestFileRows(detail: RequestFilesSource): RequestFileRow[] {
  const rows: RequestFileRow[] = []
  const seen = new Set<string>()

  for (const attachment of detail.attachments ?? []) {
    const url = attachment.url?.trim()
    if (!url) continue
    const storageKey = normalizeRequestFileStorageKey(url)
    if (storageKey && seen.has(storageKey)) continue
    if (storageKey) seen.add(storageKey)
    const name = attachment.name?.trim() || labelFromStorageKey(storageKey)
    rows.push({
      key: `attachment-${attachment.id}`,
      url,
      label: `${name} (${formatAttachmentSize(attachment.size_bytes)})`,
    })
  }

  const fileLink = detail.file_link?.trim()
  if (fileLink) {
    const storageKey = normalizeRequestFileStorageKey(fileLink)
    if (!storageKey || !seen.has(storageKey)) {
      if (storageKey) seen.add(storageKey)
      const name = labelFromStorageKey(storageKey)
      rows.push({
        key: 'file-link',
        url: fileLink,
        label: name === 'Файл' ? 'Открыть файл' : name,
      })
    }
  }

  return rows
}
