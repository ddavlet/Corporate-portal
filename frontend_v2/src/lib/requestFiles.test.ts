import { describe, expect, it } from 'vitest'
import { buildRequestFileRows, normalizeRequestFileStorageKey } from './requestFiles'

describe('normalizeRequestFileStorageKey', () => {
  it('extracts storage path from download URL', () => {
    const path = 'requests/1/99/invoice.pdf'
    const url = `https://app.example/api/files/download/?path=${encodeURIComponent(path)}`
    expect(normalizeRequestFileStorageKey(url)).toBe(path)
  })
})

describe('buildRequestFileRows', () => {
  it('merges attachments and skips duplicate file_link', () => {
    const storagePath = 'requests/1/5643/doc.pdf'
    const downloadUrl = `/api/files/download/?path=${encodeURIComponent(storagePath)}`
    const rows = buildRequestFileRows({
      file_link: downloadUrl,
      attachments: [
        {
          id: 1,
          name: 'doc.pdf',
          content_type: 'application/pdf',
          size_bytes: 1024,
          url: `https://app.example${downloadUrl}`,
        },
        {
          id: 2,
          name: 'scan.png',
          content_type: 'image/png',
          size_bytes: 2048,
          url: 'https://app.example/api/files/download/?path=requests%2F1%2F5643%2Fscan.png',
        },
      ],
    })
    expect(rows).toHaveLength(2)
    expect(rows.map((r) => r.key)).toEqual(['attachment-1', 'attachment-2'])
  })

  it('shows file_link when there are no attachments', () => {
    const rows = buildRequestFileRows({
      file_link: '/api/files/download/?path=requests%2F1%2F1%2Fold.doc',
      attachments: [],
    })
    expect(rows).toHaveLength(1)
    expect(rows[0]?.key).toBe('file-link')
    expect(rows[0]?.label).toBe('old.doc')
  })
})
