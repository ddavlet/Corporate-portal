import { act, renderHook } from '@testing-library/react'
import dayjs from 'dayjs'
import timezone from 'dayjs/plugin/timezone'
import utc from 'dayjs/plugin/utc'
import { message } from 'antd'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useRequestCreateForm } from './useRequestCreateForm'

// main.tsx extends dayjs in the app; the billing month defaults need .tz() (tashkentTime).
dayjs.extend(utc)
dayjs.extend(timezone)

const api = vi.hoisted(() => ({
  getRequestFormOptions: vi.fn(),
  listVendors: vi.fn(),
}))

vi.mock('../../lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/api')>()),
  getRequestFormOptions: (...a: unknown[]) => api.getRequestFormOptions(...a),
  listVendors: (...a: unknown[]) => api.listVendors(...a),
}))

const vendor = (id: number, name: string) => ({ id, tenant: 1, kind: 'transfer', name, inn: null, created_at: '', created_by: 1 })

function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

const wrapper = ({ children }: { children: ReactNode }) => <MemoryRouter>{children}</MemoryRouter>

async function renderOnDetails() {
  const hook = renderHook(() => useRequestCreateForm({ requestsBasePath: '/requests' }), { wrapper })
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0)
  })
  act(() => hook.result.current.selectPaymentType('Перечисление'))
  act(() => hook.result.current.goNext())
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0)
  })
  return hook
}

async function typeVendorSearch(onVendorSearch: (v: string) => void, value: string) {
  act(() => onVendorSearch(value))
  await act(async () => {
    await vi.advanceTimersByTimeAsync(300)
  })
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  api.getRequestFormOptions.mockReset().mockResolvedValue({
    payment_types: [{ payment_type: 'Перечисление', requester_ids: [], requesters: [], vendor_ids: [], payment_purposes: [] }],
  })
  api.listVendors.mockReset().mockResolvedValue([])
  vi.spyOn(message, 'warning').mockImplementation(() => undefined as never)
  vi.spyOn(message, 'error').mockImplementation(() => undefined as never)
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe('useRequestCreateForm vendor search', () => {
  it('keeps the answer to the latest search when an older one comes later', async () => {
    const older = deferred<unknown[]>()
    const latest = deferred<unknown[]>()
    api.listVendors.mockImplementation(async ({ search }: { search: string }) => {
      if (search === 'ром') return older.promise
      if (search === 'лют') return latest.promise
      return []
    })
    const { result } = await renderOnDetails()

    await typeVendorSearch(result.current.onVendorSearch, 'ром')
    await typeVendorSearch(result.current.onVendorSearch, 'лют')
    await act(async () => {
      latest.resolve([vendor(2, 'ООО Лютик')])
    })
    await act(async () => {
      older.resolve([vendor(1, 'ООО Ромашка')])
    })

    expect(result.current.vendorOptions).toEqual([{ value: 2, label: 'ООО Лютик' }])
    expect(result.current.vendorSearchLoading).toBe(false)
  })

  it('does not search after the form is gone', async () => {
    const { result, unmount } = await renderOnDetails()
    const calls = api.listVendors.mock.calls.length

    act(() => result.current.onVendorSearch('ром'))
    unmount()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300)
    })

    expect(api.listVendors.mock.calls.length).toBe(calls)
  })
})
