import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { RequestDetailContent } from './RequestDetailModal'
import type { RequestDetail } from './RequestDetailModal'

// Regression test for: clicking an attachment used to open a new tab via
// window.open() and set its location only after awaiting apiFetch()/blob().
// Browsers stopped tying that late window.open() call to the click's user
// gesture and silently blocked/dropped it, so users saw either a permanent
// about:blank tab or (once the popup was outright blocked) no request at
// all. The fix drops the new-tab dance entirely and triggers a plain
// browser download via a hidden <a download> element instead.

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

  it('downloads the file via a hidden <a download> instead of opening a new tab', async () => {
    const openSpy = vi.spyOn(window, 'open')
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)

    apiFetchMock.mockResolvedValue({
      ok: true,
      blob: () => Promise.resolve(new Blob(['pdf-bytes'])),
    })

    // The card links the requester and form settings with router links, so it needs a router.
    render(
      <MemoryRouter>
        <RequestDetailContent detail={requestDetail} />
      </MemoryRouter>,
    )

    fireEvent.click(screen.getByRole('button', { name: /Эркин шаклдаги ҳужжат\.pdf/ }))

    await waitFor(() => expect(clickSpy).toHaveBeenCalledTimes(1))

    expect(apiFetchMock).toHaveBeenCalledWith(requestDetail.attachments![0].url)
    expect(openSpy).not.toHaveBeenCalled()

    const link = clickSpy.mock.instances[0] as unknown as HTMLAnchorElement
    expect(link.getAttribute('href')).toBe('blob:mock')
    expect(link.getAttribute('download')).toBe('Эркин шаклдаги ҳужжат.pdf')
  })
})
