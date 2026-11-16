import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { PayrollCardAttentionDto } from './payrollCardApi'
import {
  refreshPayrollCardAttention,
  resetPayrollCardAttentionCache,
  usePayrollCardAttention,
} from './usePayrollCardAttention'

const attentionMock = vi.fn()

vi.mock('./payrollCardApi', () => ({
  getPayrollCardAttention: (...a: unknown[]) => attentionMock(...a),
}))

const DATA: PayrollCardAttentionDto = {
  enabled: true,
  count: 2,
  unlinked: [],
  awaiting_document: [],
  missing_card: [],
  overpaid: [],
}

describe('usePayrollCardAttention', () => {
  beforeEach(() => {
    attentionMock.mockReset()
    resetPayrollCardAttentionCache()
  })

  it('keeps the loaded review and the badge when a later refresh fails', async () => {
    attentionMock.mockResolvedValueOnce(DATA)
    const { result } = renderHook(() => usePayrollCardAttention())
    await waitFor(() => expect(result.current.data).toEqual(DATA))
    expect(result.current.count).toBe(2)

    attentionMock.mockRejectedValueOnce(new Error('Ошибка сети'))
    await act(async () => {
      await refreshPayrollCardAttention()
    })

    expect(result.current.error).toBe('Ошибка сети')
    expect(result.current.data).toEqual(DATA)
    expect(result.current.count).toBe(2)
  })

  it('has no data after a failure when nothing was loaded before', async () => {
    attentionMock.mockRejectedValueOnce(new Error('Ошибка сервера (500)'))
    const { result } = renderHook(() => usePayrollCardAttention())
    await waitFor(() => expect(result.current.error).toBe('Ошибка сервера (500)'))
    expect(result.current.data).toBeNull()
    expect(result.current.count).toBe(0)
  })
})
