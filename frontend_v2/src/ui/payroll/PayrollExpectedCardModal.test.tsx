import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PayrollExpectedCardModal } from './PayrollExpectedCardModal'

const stateMock = vi.fn()
const updateMock = vi.fn()

vi.mock('../../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../../lib/api')>('../../lib/api')
  return { ...actual, getPayrollPayoutState: (...a: unknown[]) => stateMock(...a) }
})

vi.mock('../../lib/payrollCardApi', () => ({
  updateExpectedCard: (...a: unknown[]) => updateMock(...a),
}))

const STATE = {
  can_pay: false, reason: null, accrued_total: '3000000.00', paid_total: '0.00', remaining_total: '3000000.00',
  expenses: [], request: null,
  employees: [
    {
      employee_id: 7, full_name: 'Иванов Иван', accrued: '3000000.00', paid: '0.00', remaining: '3000000.00',
      card_paid: '0.00', card_expected: '2000000.00', card_reserved: '2000000.00', cash_limit: '1000000.00',
      overpaid: '0.00',
    },
  ],
}

describe('PayrollExpectedCardModal', () => {
  beforeEach(() => {
    stateMock.mockReset()
    updateMock.mockReset()
    stateMock.mockResolvedValue(STATE)
  })

  it('prefills the expected card and saves the edited amount', async () => {
    const onSaved = vi.fn()
    const onClose = vi.fn()
    updateMock.mockResolvedValue(STATE)
    render(<PayrollExpectedCardModal open documentId={5} onClose={onClose} onSaved={onSaved} />)

    const input = (await screen.findByLabelText('Ожидается на карту: Иванов Иван')) as HTMLInputElement
    expect(input.value.replace(/\s/g, '')).toBe('2000000')
    expect(stateMock).toHaveBeenCalledWith(5)

    fireEvent.change(input, { target: { value: '1500000' } })
    fireEvent.blur(input)
    fireEvent.click(screen.getByRole('button', { name: /Сохранить/ }))

    await waitFor(() => expect(updateMock).toHaveBeenCalledWith(5, [{ employee_id: 7, amount: '1500000.00' }]))
    expect(onSaved).toHaveBeenCalledWith(STATE)
    expect(onClose).toHaveBeenCalled()
  })

  it('sends only the changed rows, so untouched prefilled amounts are not marked as manual', async () => {
    const twoEmployees = {
      ...STATE,
      employees: [
        STATE.employees[0],
        { ...STATE.employees[0], employee_id: 8, full_name: 'Петров Пётр', card_expected: '500000.00' },
      ],
    }
    stateMock.mockResolvedValue(twoEmployees)
    updateMock.mockResolvedValue(twoEmployees)
    render(<PayrollExpectedCardModal open documentId={5} onClose={() => {}} onSaved={() => {}} />)

    const input = (await screen.findByLabelText('Ожидается на карту: Петров Пётр')) as HTMLInputElement
    fireEvent.change(input, { target: { value: '700000' } })
    fireEvent.blur(input)
    fireEvent.click(screen.getByRole('button', { name: /Сохранить/ }))

    await waitFor(() => expect(updateMock).toHaveBeenCalledWith(5, [{ employee_id: 8, amount: '700000.00' }]))
  })

  it('closes without a request when nothing was changed', async () => {
    const onClose = vi.fn()
    render(<PayrollExpectedCardModal open documentId={5} onClose={onClose} onSaved={() => {}} />)

    await screen.findByLabelText('Ожидается на карту: Иванов Иван')
    fireEvent.click(screen.getByRole('button', { name: /Сохранить/ }))

    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(updateMock).not.toHaveBeenCalled()
  })

  it('shows the server error and stays open', async () => {
    const onClose = vi.fn()
    updateMock.mockRejectedValue(new Error('Ожидаемую карту можно менять только у черновика или принятого начисления.'))
    render(<PayrollExpectedCardModal open documentId={5} onClose={onClose} onSaved={() => {}} />)

    const input = (await screen.findByLabelText('Ожидается на карту: Иванов Иван')) as HTMLInputElement
    fireEvent.change(input, { target: { value: '1000000' } })
    fireEvent.blur(input)
    fireEvent.click(screen.getByRole('button', { name: /Сохранить/ }))

    expect(
      await screen.findByText('Ожидаемую карту можно менять только у черновика или принятого начисления.'),
    ).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
  })
})
