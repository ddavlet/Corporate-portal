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

describe('PayrollPayoutModal', () => {
  beforeEach(() => {
    payoutMock.mockReset()
    stateMock.mockResolvedValue({
      can_pay: true, reason: null, accrued_total: '100', paid_total: '40', remaining_total: '60', expenses: [],
      request: { id: 9, status: 'APPROVED' },
      employees: [{ employee_id: 1, full_name: 'Alice', accrued: '100', paid: '40', remaining: '60' }],
    })
  })

  it('prefills remaining, blocks amounts over remaining and has no add-employee control', async () => {
    render(<PayrollPayoutModal open documentId={3} onClose={() => {}} onDone={() => {}} />)
    const input = (await screen.findByLabelText('Сумма: Alice')) as HTMLInputElement
    expect(input.value.replace(/\s/g, '')).toBe('60')
    expect(screen.queryByText(/Добавить сотрудника/)).toBeNull()
    fireEvent.change(input, { target: { value: '61' } })
    fireEvent.blur(input)
    fireEvent.click(screen.getByRole('button', { name: /Создать расход/ }))
    await waitFor(() => expect(screen.getByText(/не более 60/)).toBeTruthy())
    expect(payoutMock).not.toHaveBeenCalled()
  })
})
