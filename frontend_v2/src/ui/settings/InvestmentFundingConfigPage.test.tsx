import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { InvestmentFundingConfigPage } from './InvestmentFundingConfigPage'

const getInvestmentFundingConfigMock = vi.fn()
const saveInvestmentFundingConfigMock = vi.fn()
const getCashRegistersMock = vi.fn()
const getBankAccountsMock = vi.fn()

vi.mock('../../lib/api', () => ({
  getInvestmentFundingConfig: (...args: unknown[]) => getInvestmentFundingConfigMock(...args),
  saveInvestmentFundingConfig: (...args: unknown[]) => saveInvestmentFundingConfigMock(...args),
  getCashRegisters: (...args: unknown[]) => getCashRegistersMock(...args),
  getBankAccounts: (...args: unknown[]) => getBankAccountsMock(...args),
}))

const baseConfig = {
  is_enabled: false,
  cash_wallet_id: 101,
  bank_wallet_id: 202,
  enabled_at: null,
  has_project_approval_chain: true,
  cash_wallet_currency: 'UZS',
}

function renderPage() {
  return render(
    <MemoryRouter>
      <InvestmentFundingConfigPage />
    </MemoryRouter>,
  )
}

describe('InvestmentFundingConfigPage', () => {
  beforeEach(() => {
    getInvestmentFundingConfigMock.mockReset()
    saveInvestmentFundingConfigMock.mockReset()
    getCashRegistersMock.mockReset().mockResolvedValue([
      { id: 1, name: 'Инвест касса', currency: 'UZS', is_active: true, wallet_id: 101 },
    ])
    getBankAccountsMock.mockReset().mockResolvedValue([
      { id: 2, label: 'Основной', account_no: '123', mfo: '1', wallet_id: 202 },
    ])
  })

  it('disables the switch and shows a hint when there is no approval chain', async () => {
    getInvestmentFundingConfigMock.mockResolvedValueOnce({ ...baseConfig, has_project_approval_chain: false })
    renderPage()

    expect(await screen.findByText('Сначала настройте согласование заявок на вложение')).toBeTruthy()
    const toggle = screen.getByRole('switch') as HTMLButtonElement
    expect(toggle.disabled).toBe(true)
  })

  it('saves the selected wallet ids', async () => {
    getInvestmentFundingConfigMock.mockResolvedValueOnce(baseConfig)
    saveInvestmentFundingConfigMock.mockResolvedValueOnce({ ...baseConfig, is_enabled: true })
    renderPage()

    const toggle = (await screen.findByRole('switch')) as HTMLButtonElement
    fireEvent.click(toggle)
    fireEvent.click(screen.getByRole('button', { name: /Сохранить/ }))

    await waitFor(() => {
      expect(saveInvestmentFundingConfigMock).toHaveBeenCalledWith({
        is_enabled: true,
        cash_wallet_id: 101,
        bank_wallet_id: 202,
      })
    })
  })
})
