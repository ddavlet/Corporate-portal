import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PayrollPayoutModal } from './PayrollPayoutModal'

const stateMock = vi.fn()
const payoutMock = vi.fn()

vi.mock('../../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../../lib/api')>('../../lib/api')
  return {
    ...actual,
    getPayrollPayoutState: (...a: unknown[]) => stateMock(...a),
    createPayrollPayout: (...a: unknown[]) => payoutMock(...a),
    listPayablePayrollDocuments: () => Promise.resolve([]),
    getCashRegisters: () =>
      Promise.resolve([
        { id: 1, tenant: 1, currency: 'UZS', name: 'Основная', code: '', description: '', is_active: true,
          sort_order: 0, is_default_for_currency: true, wallet_id: 77 },
      ]),
  }
})

// Accrued 3 000 000, card expected 2 000 000 and not arrived yet: the cash desk may pay 1 000 000 (criterion 13).
const CARD_STATE = {
  can_pay: true, reason: null, accrued_total: '3000000.00', paid_total: '0.00', remaining_total: '3000000.00',
  card_paid_total: '0.00', card_expected_total: '2000000.00', overpaid_total: '0.00', cash_limit_total: '1000000.00',
  expenses: [], request: { id: 9, status: 'APPROVED' },
  employees: [
    {
      employee_id: 1, full_name: 'Alice', accrued: '3000000.00', paid: '0.00', remaining: '3000000.00',
      card_paid: '0.00', card_expected: '2000000.00', card_reserved: '2000000.00', cash_limit: '1000000.00',
      overpaid: '0.00',
    },
  ],
}

describe('PayrollPayoutModal with card payouts', () => {
  beforeEach(() => {
    payoutMock.mockReset()
    stateMock.mockReset()
    stateMock.mockResolvedValue(CARD_STATE)
  })

  it('limits cash to cash_limit and shows the amount expected on the card', async () => {
    render(<PayrollPayoutModal open documentId={3} onClose={() => {}} onDone={() => {}} />)
    const input = (await screen.findByLabelText('Сумма: Alice')) as HTMLInputElement
    expect(input.value.replace(/\s/g, '')).toBe('1000000')
    expect(screen.getByText(/ожидается на карту 2\s000\s000,00/)).toBeInTheDocument()

    fireEvent.change(input, { target: { value: '1000001' } })
    fireEvent.blur(input)
    fireEvent.click(screen.getByRole('button', { name: /Создать расход/ }))
    await waitFor(() => expect(screen.getByText(/не более 1\s000\s000/)).toBeTruthy())
    expect(payoutMock).not.toHaveBeenCalled()
  })

  it('hides an employee whose whole remainder is expected on the card', async () => {
    stateMock.mockResolvedValue({
      ...CARD_STATE,
      employees: [
        { ...CARD_STATE.employees[0], card_expected: '3000000.00', card_reserved: '3000000.00', cash_limit: '0.00' },
        { employee_id: 2, full_name: 'Bob', accrued: '500.00', paid: '0.00', remaining: '500.00' },
      ],
    })
    render(<PayrollPayoutModal open documentId={3} onClose={() => {}} onDone={() => {}} />)
    expect(await screen.findByLabelText('Сумма: Bob')).toBeInTheDocument()
    expect(screen.queryByLabelText('Сумма: Alice')).toBeNull()
    expect(screen.getByText('Не показаны сотрудники, у которых весь остаток ожидается на карту: 1.')).toBeInTheDocument()
  })

  it('names the column «Можно из кассы», not «Остаток» as on the accrual card', async () => {
    render(<PayrollPayoutModal open documentId={3} onClose={() => {}} onDone={() => {}} />)
    await screen.findByLabelText('Сумма: Alice')
    expect(screen.getByRole('columnheader', { name: 'Можно из кассы' })).toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: 'Остаток' })).toBeNull()
    expect(screen.queryByText(/Не показаны сотрудники/)).toBeNull()
  })
})
