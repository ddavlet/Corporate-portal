import { act, renderHook } from '@testing-library/react'
import { message } from 'antd'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useMobileApprovalActions } from './useMobileApprovalActions'

const decisionMock = vi.hoisted(() => vi.fn())
const confirmPaymentMock = vi.hoisted(() => vi.fn())
const refreshActionItemsMock = vi.hoisted(() => vi.fn())

vi.mock('../../lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/api')>()),
  setRequestApprovalDecision: (...args: unknown[]) => decisionMock(...args),
  confirmPaymentViaWebApp: (...args: unknown[]) => confirmPaymentMock(...args),
}))

vi.mock('../../lib/useActionItems', () => ({
  refreshActionItems: () => refreshActionItemsMock(),
}))

/** The payload the hook gave to setRequestApprovalDecision (the helper posts it to /approvals/decision/). */
function decisionPayload(): Record<string, unknown> {
  return decisionMock.mock.calls[0][0] as Record<string, unknown>
}

describe('useMobileApprovalActions', () => {
  beforeEach(() => {
    decisionMock.mockReset()
    confirmPaymentMock.mockReset()
    refreshActionItemsMock.mockReset().mockResolvedValue(undefined)
    vi.spyOn(message, 'success').mockImplementation(() => undefined as never)
    vi.spyOn(message, 'error').mockImplementation(() => undefined as never)
    vi.spyOn(message, 'info').mockImplementation(() => undefined as never)
  })

  it('approves a step without a comment and refreshes the card and the action items', async () => {
    decisionMock.mockResolvedValue(undefined)
    const refreshDetail = vi.fn().mockResolvedValue(undefined)
    const { result } = renderHook(() => useMobileApprovalActions(77, refreshDetail))

    let ok = false
    await act(async () => {
      ok = await result.current.decide(2, 'approved')
    })

    expect(ok).toBe(true)
    expect(decisionPayload()).toEqual({ requestId: 77, step: 2, decision: 'approved' })
    expect(refreshDetail).toHaveBeenCalledTimes(1)
    expect(refreshActionItemsMock).toHaveBeenCalledTimes(1)
    expect(message.success).toHaveBeenCalledWith('Шаг одобрен')
    expect(result.current.busy).toBe(false)
  })

  it('still resolves to true when reloading the card fails after a saved decision', async () => {
    decisionMock.mockResolvedValue(undefined)
    const refreshDetail = vi.fn().mockRejectedValue(new Error('network'))
    const { result } = renderHook(() => useMobileApprovalActions(77, refreshDetail))

    await act(async () => {
      await expect(result.current.decide(2, 'approved')).resolves.toBe(true)
    })

    expect(refreshActionItemsMock).toHaveBeenCalledTimes(1)
    expect(result.current.busy).toBe(false)
  })

  it('sends the rejection reason as comment', async () => {
    decisionMock.mockResolvedValue(undefined)
    const { result } = renderHook(() => useMobileApprovalActions(77, vi.fn()))

    await act(async () => {
      await result.current.decide(1, 'rejected', '  Нет договора  ')
    })

    expect(decisionPayload()).toEqual({ requestId: 77, step: 1, decision: 'rejected', comment: 'Нет договора' })
  })

  it('leaves comment out when the reason is blank', async () => {
    decisionMock.mockResolvedValue(undefined)
    const { result } = renderHook(() => useMobileApprovalActions(77, vi.fn()))

    await act(async () => {
      await result.current.decide(1, 'rejected', '   ')
    })

    expect(decisionPayload()).toEqual({ requestId: 77, step: 1, decision: 'rejected' })
  })

  it('returns false and shows the error when the decision fails, without refreshing', async () => {
    decisionMock.mockRejectedValue(new Error('Шаг уже обработан'))
    const refreshDetail = vi.fn()
    const { result } = renderHook(() => useMobileApprovalActions(77, refreshDetail))

    let ok = true
    await act(async () => {
      ok = await result.current.decide(1, 'approved')
    })

    expect(ok).toBe(false)
    expect(message.error).toHaveBeenCalledWith('Шаг уже обработан')
    expect(refreshDetail).not.toHaveBeenCalled()
    expect(refreshActionItemsMock).not.toHaveBeenCalled()
    expect(result.current.busy).toBe(false)
  })

  it('confirms a payment with the approval id and the trimmed document number', async () => {
    confirmPaymentMock.mockResolvedValue({ request: { id: 77, status: 'PAYED' } })
    const refreshDetail = vi.fn()
    const { result } = renderHook(() => useMobileApprovalActions(77, refreshDetail))

    let ok = false
    await act(async () => {
      ok = await result.current.confirmPayment(501, ' 12345 ')
    })

    expect(ok).toBe(true)
    expect(confirmPaymentMock).toHaveBeenCalledWith({ approval_id: 501, expense_id: '12345' })
    expect(refreshDetail).toHaveBeenCalledTimes(1)
    expect(refreshActionItemsMock).toHaveBeenCalledTimes(1)
    expect(message.success).toHaveBeenCalledWith('Выплата подтверждена')
  })

  it('points to the bot when the payment step is confirmed by callback', async () => {
    confirmPaymentMock.mockRejectedValue(new Error('Step uses callback mode'))
    const { result } = renderHook(() => useMobileApprovalActions(77, vi.fn()))

    let ok = true
    await act(async () => {
      ok = await result.current.confirmPayment(501, '1')
    })

    expect(ok).toBe(false)
    expect(message.error).toHaveBeenCalledWith('Step uses callback mode')
    expect(message.info).toHaveBeenCalledWith(expect.stringContaining('бота'))
  })

  it('does nothing without a request id', async () => {
    const { result } = renderHook(() => useMobileApprovalActions(null, vi.fn()))
    let ok = true
    await act(async () => {
      ok = await result.current.decide(1, 'approved')
    })
    expect(ok).toBe(false)
    expect(decisionMock).not.toHaveBeenCalled()
  })

  it('ignores a second tap while the first decision is in flight', async () => {
    let resolveDecision: () => void = () => {}
    decisionMock.mockImplementation(() => new Promise<void>((resolve) => { resolveDecision = resolve }))
    const { result } = renderHook(() => useMobileApprovalActions(77, vi.fn().mockResolvedValue(undefined)))

    let first: Promise<boolean> = Promise.resolve(false)
    let secondResult = true
    await act(async () => {
      first = result.current.decide(2, 'approved')
      secondResult = await result.current.decide(2, 'approved')
    })

    expect(secondResult).toBe(false)
    expect(decisionMock).toHaveBeenCalledTimes(1)

    await act(async () => {
      resolveDecision()
      await first
    })
    expect(result.current.busy).toBe(false)
  })

  it('refreshes the action items and releases busy even when reloading the card fails', async () => {
    decisionMock.mockResolvedValue(undefined)
    const refreshDetail = vi.fn().mockRejectedValue(new Error('network'))
    const { result } = renderHook(() => useMobileApprovalActions(77, refreshDetail))

    await act(async () => {
      await result.current.decide(2, 'approved').catch(() => undefined)
    })

    expect(refreshActionItemsMock).toHaveBeenCalledTimes(1)
    expect(result.current.busy).toBe(false)
  })
})
