import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { RequestDetailContent } from './RequestDetailModal'
import type { RequestDetail } from './RequestDetailModal'

// Regression test for: clicking an attachment opened a new tab that stayed on
// about:blank forever, even though the download itself succeeded (200 OK).
// Root cause: window.open() was called *after* awaiting apiFetch()/blob(), by
// which point the browser no longer ties it to the click's user gesture, so
// the later `w.location.href = objectUrl` assignment is silently dropped.
// The fix opens the tab synchronously, before any await.

const apiFetchMock = vi.fn()

vi.mock('../../lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
  resendApprovalCard: vi.fn(),
}))

const requestDetail: RequestDetail = {
  id: 8234,
  title: 'Оплата поставщику',
  description: '',
  amount: 1000000,
  currency: 'UZS',
  status: 'APPROVED',
  urgency: 'Обычно',
  payment_type: 'Перечисление',
  category: 'Закуп',
  vendor: 'ZARKENT POLIMER INVEST',
  requester: 1,
  submitted_at: '2026-09-18T08:00:00Z',
  billing_date: '2026-09-01',
  approvals: [],
  attachments: [
    {
      id: 127,
      name: 'Эркин шаклдаги ҳужжат.pdf',
      content_type: 'application/pdf',
      size_bytes: 1964558,
      url: 'https://neuron.kolberg.uz/api/files/download/?path=requests%2F5%2F8234%2F%D1%84%D0%B0%D0%B9%D0%BB.pdf',
    },
  ],
}

describe('RequestDetailContent attachment download', () => {
  beforeEach(() => {
    apiFetchMock.mockReset()
    if (!('createObjectURL' in URL)) {
      Object.defineProperty(URL, 'createObjectURL', { writable: true, value: () => 'blob:mock' })
    }
    if (!('revokeObjectURL' in URL)) {
      Object.defineProperty(URL, 'revokeObjectURL', { writable: true, value: () => undefined })
    }
  })

  it('opens the tab synchronously on click, before the download resolves', async () => {
    const fakeWindow = { location: { href: '' }, close: vi.fn() }
    const openSpy = vi.spyOn(window, 'open').mockReturnValue(fakeWindow as unknown as Window)

    let resolveFetch: (value: unknown) => void = () => undefined
    apiFetchMock.mockReturnValue(
      new Promise((resolve) => {
        resolveFetch = resolve
      }),
    )

    render(<RequestDetailContent detail={requestDetail} />)

    fireEvent.click(screen.getByRole('button', { name: /файл/i }))

    // At this point the click handler has only run synchronously up to its
    // first await — window.open() must already have fired, still tied to
    // the click's user gesture.
    expect(openSpy).toHaveBeenCalledTimes(1)
    expect(openSpy).toHaveBeenCalledWith('', '_blank', 'noopener,noreferrer')
    expect(fakeWindow.location.href).toBe('')

    resolveFetch({
      ok: true,
      blob: () => Promise.resolve(new Blob(['pdf-bytes'])),
    })
    await waitFor(() => expect(fakeWindow.location.href).toBe('blob:mock'))
  })
})
