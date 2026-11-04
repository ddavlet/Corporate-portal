import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TgBankListPage } from './TgBankListPage'
import { TgBankAccountMovementsPage } from './TgBankAccountMovementsPage'

const apiFetchMock = vi.fn()
const getRevenuesMock = vi.fn()
const getOverviewMock = vi.fn()

vi.mock('../../lib/api', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
  getBankRevenues: (...args: unknown[]) => getRevenuesMock(...args),
  getBankAccountsOverview: (...args: unknown[]) => getOverviewMock(...args),
}))

vi.mock('../admin/AdminEditRecordButton', () => ({
  AdminEditRecordButton: () => null,
}))

const USD_ACCOUNT = {
  wallet_id: 12,
  bank_account_id: 112,
  label: 'Валютный',
  account_no: '20208840000000000012',
  mfo: '00001',
  is_default: false,
  account_type: 'informational',
  currency: 'USD',
  current_balance: '1500.00',
}

const EXPENSE = {
  id: 7,
  doc_date: '2026-10-01',
  process_date: '2026-10-01',
  doc_no: '15',
  vendor_name: 'Поставщик',
  debit_turnover: '250',
  payment_purpose: 'Оплата',
}

function jsonResponse(body: unknown) {
  return { ok: true, status: 200, json: async () => body }
}

function Where() {
  return <div data-testid="where">{useLocation().pathname}</div>
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/tg/bank/expenses" element={<TgBankListPage mode="expenses" />} />
        <Route
          path="/tg/bank/accounts/:walletId/:mode"
          element={
            <>
              <TgBankAccountMovementsPage />
              <Where />
            </>
          }
        />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('TgBankListPage', () => {
  beforeEach(() => {
    apiFetchMock.mockReset()
    getRevenuesMock.mockReset()
    getOverviewMock.mockReset()
    apiFetchMock.mockResolvedValue(jsonResponse([EXPENSE]))
    getRevenuesMock.mockResolvedValue([])
    getOverviewMock.mockResolvedValue([USD_ACCOUNT])
  })

  it('names the account with its number and currency and shows amounts in that currency', async () => {
    renderAt('/tg/bank/accounts/12/expenses')

    expect(await screen.findByRole('heading', { name: 'Валютный' })).toBeTruthy()
    expect(screen.getByTestId('tg-bank-account-details').textContent).toBe('20208840000000000012 · USD')
    expect(await screen.findByText(/250 USD/)).toBeTruthy()
    expect(apiFetchMock).toHaveBeenCalledWith('/api/bank/expenses/?wallet=12')
  })

  it('switches between «Все», «Расходы» and «Доходы» for the same account', async () => {
    renderAt('/tg/bank/accounts/12/all')
    await screen.findByRole('heading', { name: 'Валютный' })

    fireEvent.click(screen.getByRole('button', { name: 'Доходы' }))
    await waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/tg/bank/accounts/12/revenues'))

    fireEvent.click(screen.getByRole('button', { name: 'Расходы' }))
    await waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/tg/bank/accounts/12/expenses'))

    fireEvent.click(screen.getByRole('button', { name: 'Все' }))
    await waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/tg/bank/accounts/12/all'))
  })

  it('falls back to the wallet number when the accounts overview fails', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    getOverviewMock.mockRejectedValue(new Error('500'))
    renderAt('/tg/bank/accounts/12/expenses')

    expect(await screen.findByRole('heading', { name: 'Счёт #12' })).toBeTruthy()
    expect(await screen.findByText('250')).toBeTruthy()
  })

  it('keeps the common list unchanged without an account', async () => {
    renderAt('/tg/bank/expenses')

    expect(await screen.findByRole('heading', { name: 'Банк — расходы' })).toBeTruthy()
    expect(await screen.findByText('250')).toBeTruthy()
    expect(apiFetchMock).toHaveBeenCalledWith('/api/bank/expenses/')
    expect(getOverviewMock).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: 'Доходы' })).toBeNull()
  })
})
