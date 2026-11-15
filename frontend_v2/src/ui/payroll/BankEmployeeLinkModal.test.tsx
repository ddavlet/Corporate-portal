import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { BankEmployeeLinkModal } from './BankEmployeeLinkModal'
import type { PayrollCardUnlinkedDto } from '../../lib/payrollCardApi'

const listEmployeesMock = vi.fn()
const linkMock = vi.fn()
const assignMock = vi.fn()

vi.mock('../../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../../lib/api')>('../../lib/api')
  return { ...actual, listEmployees: (...a: unknown[]) => listEmployeesMock(...a), createEmployee: vi.fn() }
})

vi.mock('../../lib/payrollCardApi', () => ({
  linkBankEmployee: (...a: unknown[]) => linkMock(...a),
  assignCardPayout: (...a: unknown[]) => assignMock(...a),
}))

const ROW: PayrollCardUnlinkedDto = {
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
}

describe('BankEmployeeLinkModal', () => {
  beforeEach(() => {
    listEmployeesMock.mockReset()
    linkMock.mockReset()
    assignMock.mockReset()
    listEmployeesMock.mockResolvedValue([
      { id: 7, full_name: 'Иванов Иван' },
      { id: 8, full_name: 'Петров Пётр' },
    ])
  })

  it('preselects the candidate and links the bank employee', async () => {
    const onDone = vi.fn()
    const onClose = vi.fn()
    linkMock.mockResolvedValue({ id: 1, bank_employee_id: 5, employee_id: 7, full_name: 'Иванов Иван' })
    render(<BankEmployeeLinkModal row={ROW} onClose={onClose} onDone={onDone} />)

    expect(await screen.findByText('Привязать сотрудника банка')).toBeInTheDocument()
    expect(screen.getByText(/прошлые и будущие/)).toBeInTheDocument()
    // The candidate is the selected value of the employee select.
    expect(await screen.findByTitle('Иванов Иван')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Привязать' }))
    await waitFor(() => expect(linkMock).toHaveBeenCalledWith({ bank_employee_id: 5, employee_id: 7 }))
    expect(assignMock).not.toHaveBeenCalled()
    expect(onDone).toHaveBeenCalled()
    expect(onClose).toHaveBeenCalled()
  })

  it('assigns only this payout when there is no bank employee id', async () => {
    assignMock.mockResolvedValue({ payout_id: 12, employee_id: 7, document_id: null })
    render(
      <BankEmployeeLinkModal
        row={{ ...ROW, payout_id: 12, bank_employee_id: null, bank_full_name: null }}
        onClose={() => {}}
        onDone={() => {}}
      />,
    )

    expect(await screen.findByText('Отнести выплату к сотруднику')).toBeInTheDocument()
    expect(screen.getByText(/Будет отнесена только эта выплата/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Отнести' }))
    await waitFor(() => expect(assignMock).toHaveBeenCalledWith(12, 7))
    expect(linkMock).not.toHaveBeenCalled()
  })

  it('shows the 400 text and stays open', async () => {
    const onClose = vi.fn()
    linkMock.mockRejectedValue(new Error('Этот сотрудник банка уже привязан к «Петров Пётр».'))
    render(<BankEmployeeLinkModal row={ROW} onClose={onClose} onDone={() => {}} />)

    await waitFor(() => expect(listEmployeesMock).toHaveBeenCalled())
    fireEvent.click(await screen.findByRole('button', { name: 'Привязать' }))
    expect(await screen.findByText('Этот сотрудник банка уже привязан к «Петров Пётр».')).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
  })

  it('shows the candidate name, not its id, while the employee list is still loading', async () => {
    listEmployeesMock.mockReturnValue(new Promise(() => {}))
    render(<BankEmployeeLinkModal row={ROW} onClose={() => {}} onDone={() => {}} />)

    const select = await screen.findByLabelText('Сотрудник в портале')
    expect(select).toHaveAttribute('role', 'combobox')
    expect(await screen.findByTitle('Иванов Иван')).toBeInTheDocument()
    expect(screen.queryByTitle('7')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Привязать' })).toBeEnabled()
  })

  it('keeps «Привязать» disabled until an employee is chosen when there is no candidate', async () => {
    render(<BankEmployeeLinkModal row={{ ...ROW, candidate: null }} onClose={() => {}} onDone={() => {}} />)
    expect(await screen.findByRole('button', { name: 'Привязать' })).toBeDisabled()
  })
})
