import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../../../lib/api'
import type { AccountBalancesQuery, AccountBalancesResponse, BalanceAccount } from '../../../../lib/reportsApi'

const getBalanceAccountsMock = vi.fn()
const getAccountBalancesMock = vi.fn()
vi.mock('../../../../lib/reportsApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../../lib/reportsApi')>()
  return {
    ...actual,
    // Read lazily: this factory is hoisted above the mocks it calls.
    getBalanceAccounts: () => getBalanceAccountsMock(),
    getAccountBalances: (query: AccountBalancesQuery) => getAccountBalancesMock(query),
  }
})

import { AccountBalancesReport } from './AccountBalancesReport'

const BANK: BalanceAccount = {
  wallet_id: 1,
  wallet_type: 'bank',
  type_label: 'Банк',
  name: 'Основной',
  currency: 'UZS',
  account_no: '',
  hidden: false,
}
const CASH: BalanceAccount = { ...BANK, wallet_id: 2, wallet_type: 'cash', type_label: 'Касса', name: 'Главная', currency: 'USD' }

function report(account: BalanceAccount): AccountBalancesResponse {
  return {
    account,
    date_from: '2026-10-01',
    date_to: '2026-10-23',
    since_first_operation: false,
    opening_balance_day: '2026-01-01',
    opening: '700.00',
    income: '300.00',
    expense: '100.00',
    closing: '900.00',
    operations_count: 2,
    unconfirmed: { count: 0, income: '0', expense: '0' },
    days: [
      {
        date: '2026-10-05',
        opening: '700.00',
        income: '300.00',
        expense: '100.00',
        closing: '900.00',
        operations: [
          {
            source: 'bank_revenue',
            id: 1,
            date: '2026-10-05',
            at: null,
            direction: 'in',
            amount: '300.00',
            title: 'Оплата по договору',
            counterparty: 'ООО Альфа',
            document: 'П-1',
            counted: true,
            balance_after: '1000.00',
          },
          {
            source: 'bank_expense',
            id: 2,
            date: '2026-10-05',
            at: null,
            direction: 'out',
            amount: '100.00',
            title: 'Комиссия банка',
            counterparty: '',
            document: '7',
            counted: true,
            balance_after: '900.00',
          },
        ],
      },
    ],
  }
}

function renderReport() {
  return render(
    <MemoryRouter initialEntries={['/reports/professional/balances?mode=period&start=2026-10-01&end=2026-10-23']}>
      <AccountBalancesReport report="balances" onOpenRules={null} rulesVersion={0} />
    </MemoryRouter>,
  )
}

describe('AccountBalancesReport', () => {
  beforeEach(() => {
    getBalanceAccountsMock.mockReset().mockResolvedValue([BANK, CASH])
    getAccountBalancesMock.mockReset().mockImplementation((query: AccountBalancesQuery) =>
      query.wallet === BANK.wallet_id
        ? Promise.resolve(report(BANK))
        : Promise.reject(new ApiError(500, 'Не удалось построить отчёт')),
    )
  })

  it('shows the period totals and days of the first account', async () => {
    renderReport()
    expect(await screen.findByText('Остаток на конец')).toBeInTheDocument()
    expect(getAccountBalancesMock).toHaveBeenCalledWith({ wallet: 1, dateFrom: '2026-10-01', dateTo: '2026-10-23' })
    expect(screen.getAllByText('900').length).toBeGreaterThan(0)
    expect(screen.getAllByText('UZS').length).toBe(4)
    expect(screen.getByText('05.10.2026')).toBeInTheDocument()
    expect(screen.getByText(/остатка счёта на 01\.01\.2026 плюс/)).toBeInTheDocument()
  })

  it('opens a day into its operations with the balance after each one', async () => {
    renderReport()
    fireEvent.click(await screen.findByText('05.10.2026'))
    expect(await screen.findByText('Комиссия банка')).toBeInTheDocument()
    expect(screen.getByText('1 000', { normalizer: (text) => text.replace(/\s/g, ' ') })).toBeInTheDocument()
    // Bank lines have no time of day: no «Время» column.
    expect(screen.queryByText('Время')).not.toBeInTheDocument()
  })

  it('never shows another account’s figures under the newly selected account', async () => {
    renderReport()
    await screen.findByText('Остаток на конец')
    fireEvent.click(screen.getByText('Касса'))
    expect(await screen.findByText('Не удалось построить отчёт')).toBeInTheDocument()
    expect(screen.queryByText('Остаток на конец')).not.toBeInTheDocument()
    expect(screen.queryAllByText('900')).toHaveLength(0)
    expect(screen.queryAllByText('UZS')).toHaveLength(0)
  })

  it('refreshes the report without reloading the accounts or blanking the page', async () => {
    renderReport()
    await screen.findByText('Остаток на конец')
    fireEvent.click(screen.getByRole('button', { name: 'Обновить' }))
    await waitFor(() => expect(getAccountBalancesMock).toHaveBeenCalledTimes(2))
    expect(getBalanceAccountsMock).toHaveBeenCalledTimes(1)
    expect(screen.getByText('Остаток на конец')).toBeInTheDocument()
  })

  it('explains an empty account list (no access to bank, cash or card)', async () => {
    getBalanceAccountsMock.mockResolvedValue([])
    renderReport()
    expect(await screen.findByText(/Нет доступных счетов/)).toBeInTheDocument()
    expect(getAccountBalancesMock).not.toHaveBeenCalled()
  })
})
