import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TgBankPage } from './TgBankPage'

const getOverviewMock = vi.fn()
const getUntrackedMock = vi.fn()

vi.mock('../../lib/api', () => ({
  getBankAccountsOverview: (...args: unknown[]) => getOverviewMock(...args),
  getKapitalbankUntrackedAccounts: (...args: unknown[]) => getUntrackedMock(...args),
}))

const ACCOUNT = (walletId: number, label: string, accountType: 'controlled' | 'informational' | 'service') => ({
  wallet_id: walletId,
  bank_account_id: walletId + 100,
  label,
  account_no: `2020800000000000000${walletId}`,
  mfo: '00001',
  is_default: false,
  account_type: accountType,
  currency: 'UZS',
  current_balance: '1500.00',
})

function Where() {
  return <div data-testid="where">{useLocation().pathname}</div>
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/tg/bank']}>
      <Routes>
        <Route path="/tg/bank" element={<TgBankPage />} />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('TgBankPage', () => {
  beforeEach(() => {
    getOverviewMock.mockReset()
    getUntrackedMock.mockReset()
    vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  it('lists accounts and opens account movements', async () => {
    getOverviewMock.mockResolvedValue([ACCOUNT(12, 'Валютный', 'informational'), ACCOUNT(11, 'Основной', 'controlled')])
    getUntrackedMock.mockResolvedValue([])
    renderPage()

    fireEvent.click(await screen.findByText(/Основной/))
    await waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/tg/bank/accounts/11/all'))
  })

  it('keeps common section links when the account requests fail', async () => {
    getOverviewMock.mockRejectedValue(new Error('500'))
    getUntrackedMock.mockRejectedValue(new Error('500'))
    renderPage()

    fireEvent.click(await screen.findByText('Расходы'))
    await waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/tg/bank/expenses'))
  })
})
