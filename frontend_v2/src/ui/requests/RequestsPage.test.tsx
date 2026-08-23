import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { RequestsPage } from './RequestsPage'

// Regression test for: editing an existing request only offered vendors that were
// already visible in the currently loaded table rows (`optionize(rows.map(r => r.vendor))`),
// instead of searching the tenant's vendor directory. A vendor not present among the
// loaded rows (e.g. "ANOR BANK" on request #7766) could never be selected, and the PATCH
// payload never carried `vendor_ref`, so the FK link was never updated either.

const apiFetchMock = vi.fn()
const getRequestFormOptionsMock = vi.fn()
const getRequestCategoriesMock = vi.fn()
const getRequestVendorsMock = vi.fn()
const listVendorsMock = vi.fn()
const getSettingsAccessMock = vi.fn()
const getUserPreferencesMock = vi.fn()
const setUserPreferenceMock = vi.fn()

vi.mock('../../lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
  copyPortalRequest: vi.fn(),
  getRequestFormOptions: (...args: unknown[]) => getRequestFormOptionsMock(...args),
  getRequestCategories: (...args: unknown[]) => getRequestCategoriesMock(...args),
  getRequestVendors: (...args: unknown[]) => getRequestVendorsMock(...args),
  listVendors: (...args: unknown[]) => listVendorsMock(...args),
  parseErrorBody: vi.fn().mockResolvedValue('error'),
  submitRequestForApproval: vi.fn(),
  resendApprovalCard: vi.fn(),
  createRequestComment: vi.fn(),
  getSettingsAccess: (...args: unknown[]) => getSettingsAccessMock(...args),
  getUserPreferences: (...args: unknown[]) => getUserPreferencesMock(...args),
  setUserPreference: (...args: unknown[]) => setUserPreferenceMock(...args),
}))

const requestRow = {
  id: 7766,
  title: 'Возврат инвестиций',
  description: '',
  amount: 1000000,
  currency: 'UZS',
  status: 'PAYED',
  urgency: 'Обычно',
  payment_type: 'Перечисление',
  category: 'Возврат инвестиций',
  vendor: 'DAVLETYAROV RAVSHAN BATIROVICH',
  requester: 1,
  submitted_at: '2026-08-18T10:43:45Z',
  billing_date: '2026-08-01',
}

const requestDetail = {
  ...requestRow,
  vendor_ref: 546,
  requester: 1,
  approvals: [],
  comments: [],
}

vi.mock('../../lib/useInfiniteList', () => ({
  useInfiniteList: () => ({
    items: [requestRow],
    setItems: vi.fn(),
    loading: false,
    loadingMore: false,
    error: null,
    hasMore: false,
    loadMore: vi.fn(),
    reload: vi.fn(),
    sentinelRef: { current: null },
    pagesLoaded: 1,
  }),
  useRestoreInfinitePages: () => {},
}))

function renderPage() {
  return render(
    <MemoryRouter>
      <RequestsPage />
    </MemoryRouter>,
  )
}

describe('RequestsPage vendor edit', () => {
  beforeEach(() => {
    apiFetchMock.mockReset()
    getRequestFormOptionsMock.mockReset().mockResolvedValue({
      is_tenant_admin: true,
      is_tenant_director: false,
      contracts_module_effective: false,
      requester_candidates: [],
      payment_types: [
        {
          payment_type: 'Перечисление',
          requester_ids: [],
          requesters: [],
          vendor_ids: [],
          payment_purposes: [],
        },
      ],
    })
    getRequestCategoriesMock.mockReset().mockResolvedValue([])
    getRequestVendorsMock.mockReset().mockResolvedValue([])
    getSettingsAccessMock.mockReset().mockResolvedValue({ can_open_admin: false })
    getUserPreferencesMock.mockReset().mockResolvedValue({})
    setUserPreferenceMock.mockReset().mockResolvedValue({})
    listVendorsMock.mockReset().mockResolvedValue([
      {
        id: 146,
        tenant: 3,
        kind: 'transfer',
        name: 'ТОШКЕНТ Ш., "ANOR BANK" АКЦИЯДОРЛИК ЖАМИЯТИ',
        inn: '207324986',
        account_number: '23120000700001180000',
        created_at: '2026-05-20T13:28:29Z',
        created_by: 1,
      },
      {
        id: 546,
        tenant: 3,
        kind: 'transfer',
        name: 'DAVLETYAROV RAVSHAN BATIROVICH',
        inn: '0000',
        account_number: null,
        created_at: '2026-04-01T00:00:00Z',
        created_by: 1,
      },
    ])

    apiFetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === '/api/requests/7766/' && init?.method === 'PATCH') {
        return { ok: true, json: async () => ({}) } as Response
      }
      if (url === '/api/requests/7766/') {
        return { ok: true, json: async () => requestDetail } as Response
      }
      return { ok: true, json: async () => ({}) } as Response
    })
  })

  it('loads vendor options from the vendor directory (not just the visible rows) when editing', async () => {
    renderPage()

    fireEvent.click(await screen.findByText('7766'))
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalledWith('/api/requests/7766/'))
    await screen.findByText('DAVLETYAROV RAVSHAN BATIROVICH')

    const editButton = await screen.findByRole('button', { name: 'Редактировать' })
    fireEvent.click(editButton)

    // The old bug: options came only from `rows` on screen, which never includes a
    // vendor used on a different request. The fix routes through the vendor directory.
    await waitFor(() =>
      expect(listVendorsMock).toHaveBeenCalledWith({ kind: 'transfer', search: '' }),
    )
  })

  it('sends vendor_ref in the save payload so the FK link is actually persisted', async () => {
    renderPage()

    fireEvent.click(await screen.findByText('7766'))
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalledWith('/api/requests/7766/'))
    await screen.findByText('DAVLETYAROV RAVSHAN BATIROVICH')

    fireEvent.click(await screen.findByRole('button', { name: 'Редактировать' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Сохранить' }))

    await waitFor(() => {
      const patchCall = apiFetchMock.mock.calls.find(
        ([url, init]) => url === '/api/requests/7766/' && init?.method === 'PATCH',
      )
      expect(patchCall).toBeTruthy()
      const body = JSON.parse((patchCall![1] as RequestInit).body as string)
      expect(body.vendor_ref).toBe(546)
    })
  })
})
