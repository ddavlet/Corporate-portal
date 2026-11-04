import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useRequestInvestmentIds } from './useRequestInvestments'

const getInvestmentFundingConfigMock = vi.fn()
const getProjectInvestmentsBySourceRequestMock = vi.fn()

vi.mock('../../lib/api', () => ({
  getInvestmentFundingConfig: (...args: unknown[]) => getInvestmentFundingConfigMock(...args),
  getProjectInvestmentsBySourceRequest: (...args: unknown[]) => getProjectInvestmentsBySourceRequestMock(...args),
}))

const investRequest = { id: 41, payment_type: 'Инвест. наличные', payment_purpose: '' }

describe('useRequestInvestmentIds', () => {
  beforeEach(() => {
    getInvestmentFundingConfigMock.mockReset()
    getProjectInvestmentsBySourceRequestMock.mockReset().mockResolvedValue([{ id: 7 }])
  })

  it('fetches investments only when the funding mode is enabled', async () => {
    getInvestmentFundingConfigMock.mockResolvedValue({ is_enabled: true })
    const { result } = renderHook(() => useRequestInvestmentIds(investRequest))
    await waitFor(() => expect(result.current).toEqual([7]))
    expect(getProjectInvestmentsBySourceRequestMock).toHaveBeenCalledWith(41)
  })

  it('does not fetch investments when the funding mode is disabled', async () => {
    getInvestmentFundingConfigMock.mockResolvedValue({ is_enabled: false })
    const { result } = renderHook(() => useRequestInvestmentIds(investRequest))
    await waitFor(() => expect(getInvestmentFundingConfigMock).toHaveBeenCalled())
    await Promise.resolve()
    expect(getProjectInvestmentsBySourceRequestMock).not.toHaveBeenCalled()
    expect(result.current).toEqual([])
  })

  it('does not even read the funding config for regular requests', () => {
    renderHook(() => useRequestInvestmentIds({ id: 42, payment_type: 'Перечисление', payment_purpose: '' }))
    expect(getInvestmentFundingConfigMock).not.toHaveBeenCalled()
    expect(getProjectInvestmentsBySourceRequestMock).not.toHaveBeenCalled()
  })
})
