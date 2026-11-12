import { act, renderHook, waitFor } from '@testing-library/react'
import { message } from 'antd'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useInvestmentFromRequests } from './useInvestmentFromRequests'

const api = vi.hoisted(() => ({
  getFundingPool: vi.fn(),
  createInvestmentsFromRequests: vi.fn(),
}))

vi.mock('../../lib/api', () => ({
  getFundingPool: (...a: unknown[]) => api.getFundingPool(...a),
  createInvestmentsFromRequests: (...a: unknown[]) => api.createInvestmentsFromRequests(...a),
}))

function req(id: number, over: Record<string, unknown> = {}) {
  return {
    id,
    submitted_at: '2026-10-01T10:00:00Z',
    kind: 'expense',
    payment_type: 'Наличные',
    payment_purpose: 'Закупка',
    description: 'компьютер',
    amount: '5000000',
    currency: 'UZS',
    status: 'approved',
    is_payed: false,
    ...over,
  }
}

const POOL = {
  cash: { requests: [req(10), req(11, { amount: '1000000' })], totals: [] },
  bank_transfer: { requests: [req(20, { payment_type: 'Перечисление', amount: '3000000' })], totals: [] },
  approval_chain_ok: true,
}

function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

async function renderLoaded() {
  const hook = renderHook(() => useInvestmentFromRequests())
  await waitFor(() => expect(hook.result.current.pool).not.toBeNull())
  return hook
}

let successSpy: ReturnType<typeof vi.spyOn>
let errorSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  api.getFundingPool.mockReset().mockResolvedValue(POOL)
  api.createInvestmentsFromRequests.mockReset().mockResolvedValue({ investments: [{ id: 77 }] })
  successSpy = vi.spyOn(message, 'success').mockImplementation(() => undefined as never)
  errorSpy = vi.spyOn(message, 'error').mockImplementation(() => undefined as never)
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('useInvestmentFromRequests', () => {
  it('selects every request of both methods after loading', async () => {
    const { result } = await renderLoaded()

    expect([...result.current.selected].sort()).toEqual([10, 11, 20])
    expect(result.current.method).toBe('cash')
    expect(result.current.chosen.map((r) => r.id)).toEqual([10, 11])
    expect(result.current.totals).toEqual([{ currency: 'UZS', amount: 6000000, count: 2 }])
    expect(result.current.canSubmit).toBe(true)
  })

  it('previews the generated description and drops the edit on a method change', async () => {
    const { result } = await renderLoaded()
    expect(result.current.comment).toBe('На основании заявок №10, №11. №10 — компьютер; №11 — компьютер')

    act(() => result.current.setComment('Своё описание'))
    expect(result.current.comment).toBe('Своё описание')

    act(() => result.current.setMethod('bank_transfer'))
    expect(result.current.comment).toBe('На основании заявки №20. №20 — компьютер')
    act(() => result.current.setMethod('cash'))
    expect(result.current.comment).toBe(result.current.generated)
  })

  it('sends an empty comment without an edit', async () => {
    const { result } = await renderLoaded()
    await act(async () => {
      await result.current.submit()
    })
    expect(api.createInvestmentsFromRequests).toHaveBeenCalledWith({ funding_method: 'cash', request_ids: [10, 11], comment: '' })
  })

  it('sends the edited comment', async () => {
    const { result } = await renderLoaded()
    act(() => result.current.setComment('Своё описание'))
    await act(async () => {
      await result.current.submit()
    })
    expect(api.createInvestmentsFromRequests.mock.calls[0][0]).toMatchObject({ comment: 'Своё описание' })
  })

  it('toggles one request', async () => {
    const { result } = await renderLoaded()
    act(() => result.current.toggleOne(10))
    expect(result.current.chosen.map((r) => r.id)).toEqual([11])
    act(() => result.current.toggleOne(11))
    expect(result.current.chosen).toEqual([])
    expect(result.current.canSubmit).toBe(false)
    act(() => result.current.toggleOne(10))
    expect(result.current.chosen.map((r) => r.id)).toEqual([10])
  })

  it('sends one request on a double submit', async () => {
    const pending = deferred<{ investments: { id: number }[] }>()
    api.createInvestmentsFromRequests.mockReturnValue(pending.promise)
    const { result } = await renderLoaded()

    let first!: Promise<unknown>
    let second: unknown
    await act(async () => {
      first = result.current.submit()
      second = await result.current.submit()
    })
    expect(second).toBeNull()
    expect(result.current.submitting).toBe(true)
    expect(result.current.canSubmit).toBe(false)

    await act(async () => {
      pending.resolve({ investments: [{ id: 78 }] })
      await first
    })
    expect(api.createInvestmentsFromRequests).toHaveBeenCalledTimes(1)
  })

  it('keeps the result and sends nothing after a success', async () => {
    const { result } = await renderLoaded()
    let created: unknown
    await act(async () => {
      created = await result.current.submit()
    })
    expect(created).toEqual([{ id: 77 }])
    expect(result.current.created).toEqual([{ id: 77 }])
    expect(successSpy).toHaveBeenCalledWith('Создано вложений: №77')
    expect(result.current.canSubmit).toBe(false)

    let again: unknown
    await act(async () => {
      again = await result.current.submit()
    })
    expect(again).toBeNull()
    expect(api.createInvestmentsFromRequests).toHaveBeenCalledTimes(1)
  })

  it('keeps the selection and the edit when the server refuses', async () => {
    api.createInvestmentsFromRequests.mockRejectedValue(new Error('Заявка уже собрана'))
    const { result } = await renderLoaded()
    act(() => result.current.toggleOne(11))
    act(() => result.current.setComment('Своё описание'))

    let created: unknown
    await act(async () => {
      created = await result.current.submit()
    })

    expect(created).toBeNull()
    expect(errorSpy).toHaveBeenCalledWith('Заявка уже собрана')
    expect(result.current.created).toBeNull()
    expect(result.current.chosen.map((r) => r.id)).toEqual([10])
    expect(result.current.comment).toBe('Своё описание')
    expect(result.current.canSubmit).toBe(true)
  })

  it('selects everything again after a reload that follows a failed load', async () => {
    api.getFundingPool.mockRejectedValueOnce(new Error('Нет инвестиционного режима'))
    const { result } = renderHook(() => useInvestmentFromRequests())
    await waitFor(() => expect(result.current.loadError).toBe('Нет инвестиционного режима'))
    expect(result.current.pool).toBeNull()
    expect(result.current.loading).toBe(false)

    act(() => result.current.reload())
    expect(result.current.loading).toBe(true)
    await waitFor(() => expect(result.current.pool).not.toBeNull())
    expect(result.current.loadError).toBeNull()
    expect([...result.current.selected].sort()).toEqual([10, 11, 20])
  })
})
