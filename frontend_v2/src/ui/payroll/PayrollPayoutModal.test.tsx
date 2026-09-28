import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PayrollPayoutModal } from './PayrollPayoutModal'

const stateMock = vi.fn()
const payoutMock = vi.fn()
const payableMock = vi.fn()

vi.mock('../../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../../lib/api')>('../../lib/api')
  return {
    ...actual,
    getPayrollPayoutState: (...a: unknown[]) => stateMock(...a),
    createPayrollPayout: (...a: unknown[]) => payoutMock(...a),
    listPayablePayrollDocuments: (...a: unknown[]) => payableMock(...a),
    getCashRegisters: () =>
      Promise.resolve([
        { id: 1, tenant: 1, currency: 'UZS', name: 'Основная', code: '', description: '', is_active: true,
          sort_order: 0, is_default_for_currency: true, wallet_id: 77 },
      ]),
  }
})

function clickSelectOption(pattern: RegExp) {
  const option = Array.from(document.querySelectorAll('.ant-select-item-option')).find((el) =>
    pattern.test(el.textContent ?? ''),
  )
  if (!option) throw new Error(`option matching ${pattern} not found`)
  fireEvent.click(option)
}

describe('PayrollPayoutModal', () => {
  beforeEach(() => {
    payoutMock.mockReset()
    payableMock.mockReset()
    payableMock.mockResolvedValue([])
    stateMock.mockReset()
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

  it('clears a stale load error when switching to a document that resolves (picker flow)', async () => {
    payableMock.mockResolvedValue([
      { id: 1, label: 'Начисление A', period_month: null, kind: null, remaining_total: '50' },
      { id: 2, label: 'Начисление B', period_month: null, kind: null, remaining_total: '70' },
    ])
    stateMock.mockImplementation((id: number) =>
      id === 1
        ? Promise.reject(new Error('Ошибка А'))
        : Promise.resolve({
            can_pay: true, reason: null, accrued_total: '70', paid_total: '0', remaining_total: '70', expenses: [],
            request: { id: 10, status: 'APPROVED' },
            employees: [{ employee_id: 2, full_name: 'Bob', accrued: '70', paid: '0', remaining: '70' }],
          }),
    )

    render(<PayrollPayoutModal open onClose={() => {}} onDone={() => {}} />)

    const docSelect = (await screen.findAllByRole('combobox'))[0]
    fireEvent.mouseDown(docSelect)
    await waitFor(() =>
      expect(Array.from(document.querySelectorAll('.ant-select-item-option')).length).toBeGreaterThan(0),
    )
    clickSelectOption(/Начисление A/)
    await waitFor(() => expect(screen.getByText(/Ошибка А/)).toBeTruthy())

    fireEvent.mouseDown(docSelect)
    await waitFor(() =>
      expect(Array.from(document.querySelectorAll('.ant-select-item-option')).length).toBeGreaterThan(0),
    )
    clickSelectOption(/Начисление B/)

    await waitFor(() => expect(screen.queryByText(/Ошибка А/)).toBeNull())
    expect(await screen.findByLabelText('Сумма: Bob')).toBeTruthy()
  })
})
