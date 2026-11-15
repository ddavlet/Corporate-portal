import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PayrollCardReviewPage } from './PayrollCardReviewPage'
import type { PayrollCardAttentionDto, PayrollCardUnlinkedDto } from '../lib/payrollCardApi'

type HookState = {
  data: PayrollCardAttentionDto | null
  loading: boolean
  error: string | null
}

let hookState: HookState
const refreshMock = vi.fn()

vi.mock('../lib/usePayrollCardAttention', () => ({
  usePayrollCardAttention: () => ({
    ...hookState,
    count: hookState.data?.enabled ? hookState.data.count : 0,
    refresh: () => refreshMock(),
  }),
}))

// The modal itself is covered in BankEmployeeLinkModal.test.tsx; here only which payout it gets.
vi.mock('./payroll/BankEmployeeLinkModal', async () => {
  const actual = await vi.importActual<typeof import('./payroll/BankEmployeeLinkModal')>(
    './payroll/BankEmployeeLinkModal',
  )
  return {
    ...actual,
    BankEmployeeLinkModal: ({ row }: { row: PayrollCardUnlinkedDto | null }) =>
      row ? <div data-testid="link-modal">{`payout:${row.payout_id}`}</div> : null,
  }
})

const EMPTY: PayrollCardAttentionDto = {
  enabled: true,
  count: 0,
  unlinked: [],
  awaiting_document: [],
  missing_card: [],
  overpaid: [],
}

function unlinked(overrides: Partial<PayrollCardUnlinkedDto> = {}): PayrollCardUnlinkedDto {
  return {
    payout_id: 11,
    bank_employee_id: 5,
    bank_full_name: 'IVANOV IVAN',
    name_from_purpose: 'Ivanov Ivan',
    masked_card: '8600********7777',
    card_account_masked: '2020…1234',
    amount: '2000000.00',
    paid_on: '2026-10-02',
    batch_num: '777',
    batch_date: '2026-10-02',
    candidate: { id: 7, full_name: 'Иванов Иван' },
    ...overrides,
  }
}

function renderPage() {
  return render(
    <MemoryRouter>
      <PayrollCardReviewPage />
    </MemoryRouter>,
  )
}

function section(name: string) {
  return screen.getByRole('region', { name })
}

describe('PayrollCardReviewPage', () => {
  beforeEach(() => {
    refreshMock.mockReset()
    hookState = { data: EMPTY, loading: false, error: null }
  })

  it('says «Всё разобрано» when nothing needs a decision', () => {
    renderPage()
    expect(screen.getByText('Всё разобрано')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Без привязки' })).not.toBeInTheDocument()
  })

  it('shows empty states of the other sections when only one has rows', () => {
    hookState.data = { ...EMPTY, count: 1, unlinked: [unlinked()] }
    renderPage()
    expect(within(section('Без привязки')).getByText('IVANOV IVAN')).toBeInTheDocument()
    expect(within(section('Ждут начисления')).getByText('Нет выплат, ждущих начисления')).toBeInTheDocument()
    expect(within(section('Переплаты')).getByText('Переплат нет')).toBeInTheDocument()
    expect(within(section('Ожидалась карта, не пришла')).getByText('Все ожидаемые выплаты пришли')).toBeInTheDocument()
  })

  it('shows the empty state of «Без привязки» when other sections have rows', () => {
    hookState.data = {
      ...EMPTY,
      count: 1,
      awaiting_document: [
        { payout_id: 3, employee_id: 7, full_name: 'Петров Пётр', period_month: '2026-10-01', amount: '100.00', paid_on: '2026-11-02' },
      ],
    }
    renderPage()
    expect(within(section('Без привязки')).getByText('Все выплаты привязаны')).toBeInTheDocument()
    expect(within(section('Ждут начисления')).getByText('Петров Пётр')).toBeInTheDocument()
  })

  it('opens the link mode for a payout with a bank employee id and the assign mode without it', () => {
    hookState.data = {
      ...EMPTY,
      count: 2,
      unlinked: [
        unlinked(),
        unlinked({ payout_id: 12, bank_employee_id: null, bank_full_name: null, masked_card: null, candidate: null }),
      ],
    }
    renderPage()
    const block = section('Без привязки')
    expect(within(block).getByText('из назначения, без кода сотрудника')).toBeInTheDocument()

    fireEvent.click(within(block).getByRole('button', { name: 'Привязать' }))
    expect(screen.getByTestId('link-modal')).toHaveTextContent('payout:11')

    fireEvent.click(within(block).getByRole('button', { name: 'Отнести эту выплату' }))
    expect(screen.getByTestId('link-modal')).toHaveTextContent('payout:12')
  })

  it('lists overpayments with the breakdown and a link to the accrual', () => {
    hookState.data = {
      ...EMPTY,
      count: 1,
      overpaid: [
        {
          document_id: 42,
          document_label: 'ЗП-42',
          period_month: '2026-09-01',
          employee_id: 7,
          full_name: 'Иванов Иван',
          accrued: '3000000.00',
          cash: '1500000.00',
          card: '2000000.00',
          overpaid: '500000.00',
        },
      ],
    }
    renderPage()
    const block = section('Переплаты')
    expect(within(block).getByRole('link', { name: 'ЗП-42' })).toHaveAttribute('href', '/payroll/42')
    expect(within(block).getByText(/3\s000\s000,00/)).toBeInTheDocument()
    expect(within(block).getByText(/1\s500\s000,00/)).toBeInTheDocument()
    expect(within(block).getByText(/2\s000\s000,00/)).toBeInTheDocument()
    expect(within(block).getByText(/^500\s000,00$/)).toBeInTheDocument()
  })

  it('lists expected card payouts that did not arrive', () => {
    hookState.data = {
      ...EMPTY,
      count: 1,
      missing_card: [{ document_id: 9, document_label: 'ЗП-9', employee_id: 7, full_name: 'Иванов Иван', expected: '2000000.00' }],
    }
    renderPage()
    const block = section('Ожидалась карта, не пришла')
    expect(within(block).getByRole('link', { name: 'ЗП-9' })).toHaveAttribute('href', '/payroll/9')
  })

  it('names both reasons (no role or module off, 403/404) instead of blaming the role only', () => {
    hookState.data = null
    renderPage()
    expect(screen.getByText(/нужна роль «Начисления ЗП» и включённый модуль/)).toBeInTheDocument()
    expect(screen.queryByText(/доступен только с ролью/)).not.toBeInTheDocument()
  })

  it('shows the full group size and says only the first rows are listed', () => {
    hookState.data = {
      ...EMPTY,
      count: 250,
      counts: { unlinked: 250, awaiting_document: 0, missing_card: 0, overpaid: 0 },
      unlinked: [unlinked(), unlinked({ payout_id: 12 })],
    }
    renderPage()
    const block = section('Без привязки')
    expect(within(block).getByText('250')).toBeInTheDocument()
    expect(within(block).getByText(/Показаны первые 2 из 250/)).toBeInTheDocument()
  })

  it('does not mention a cut when the whole group is listed', () => {
    hookState.data = {
      ...EMPTY,
      count: 1,
      counts: { unlinked: 1, awaiting_document: 0, missing_card: 0, overpaid: 0 },
      unlinked: [unlinked()],
    }
    renderPage()
    expect(screen.queryByText(/Показаны первые/)).not.toBeInTheDocument()
  })

  it('titles the action column of «Без привязки»', () => {
    hookState.data = { ...EMPTY, count: 1, unlinked: [unlinked()] }
    renderPage()
    expect(within(section('Без привязки')).getByRole('columnheader', { name: 'Действие' })).toBeInTheDocument()
  })

  it('keeps the loaded review and warns when a refresh failed', () => {
    hookState = { data: { ...EMPTY, count: 1, unlinked: [unlinked()] }, loading: false, error: 'Ошибка сети' }
    renderPage()
    expect(screen.getByText('Не удалось обновить разбор, показаны прежние данные')).toBeInTheDocument()
    expect(within(section('Без привязки')).getByText('IVANOV IVAN')).toBeInTheDocument()
    expect(screen.queryByText('Не удалось загрузить разбор выплат на карту')).not.toBeInTheDocument()
  })

  it('says card accounting is off for the company', () => {
    hookState.data = { ...EMPTY, enabled: false }
    renderPage()
    expect(screen.getByText('Учёт выплат на карту для компании не включён')).toBeInTheDocument()
  })

  it('shows a load error', () => {
    hookState = { data: null, loading: false, error: 'Ошибка сервера (500)' }
    renderPage()
    expect(screen.getByText('Не удалось загрузить разбор выплат на карту')).toBeInTheDocument()
  })

  it('refreshes on «Обновить»', () => {
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: /Обновить/ }))
    expect(refreshMock).toHaveBeenCalled()
  })
})
