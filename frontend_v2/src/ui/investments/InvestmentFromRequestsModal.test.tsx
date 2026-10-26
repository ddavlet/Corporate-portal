import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { InvestmentFromRequestsModal } from './InvestmentFromRequestsModal'

const getFundingPoolMock = vi.fn()
const createInvestmentsFromRequestsMock = vi.fn()

vi.mock('../../lib/api', () => ({
  getFundingPool: (...args: unknown[]) => getFundingPoolMock(...args),
  createInvestmentsFromRequests: (...args: unknown[]) => createInvestmentsFromRequestsMock(...args),
}))

function req(id: number, over: Record<string, unknown> = {}) {
  return {
    id,
    submitted_at: '2026-10-01T10:00:00Z',
    kind: 'expense',
    payment_type: 'Наличные',
    payment_purpose: 'Закупка',
    description: 'компьютер',
    amount: '5000000',
    currency: 'UZS',
    status: 'approved',
    is_payed: false,
    ...over,
  }
}

function renderModal() {
  return render(
    <InvestmentFromRequestsModal
      open
      onCancel={() => {}}
      onCreated={() => {}}
      usesCompanies={false}
      companies={[]}
    />,
  )
}

describe('InvestmentFromRequestsModal', () => {
  beforeEach(() => {
    getFundingPoolMock.mockReset()
    createInvestmentsFromRequestsMock.mockReset()
  })

  it('shows empty state for a tab without requests', async () => {
    getFundingPoolMock.mockResolvedValue({
      cash: { requests: [], totals: [] },
      bank_transfer: { requests: [], totals: [] },
      approval_chain_ok: true,
    })
    renderModal()
    expect(await screen.findByText('Нет заявок для сбора')).toBeTruthy()
  })

  it('submits selected cash requests and disables the button with nothing selected', async () => {
    getFundingPoolMock.mockResolvedValue({
      cash: { requests: [req(10)], totals: [] },
      bank_transfer: { requests: [], totals: [] },
      approval_chain_ok: true,
    })
    createInvestmentsFromRequestsMock.mockResolvedValue({ investments: [{ id: 77 }] })
    renderModal()

    const button = (await screen.findByRole('button', { name: 'Создать вложение' })) as HTMLButtonElement
    await waitFor(() => expect(button.disabled).toBe(false))
    expect(screen.getByText(/Итого: 5\s?000\s?000 UZS \(1 заявка\)/)).toBeTruthy()

    const checkboxes = screen.getAllByRole('checkbox')
    // [0] — «выбрать все» таблицы расходов, [1] — строка №10
    fireEvent.click(checkboxes[1])
    await waitFor(() => expect(button.disabled).toBe(true))
    fireEvent.click(checkboxes[1])
    await waitFor(() => expect(button.disabled).toBe(false))

    fireEvent.click(button)
    await waitFor(() => expect(createInvestmentsFromRequestsMock).toHaveBeenCalledTimes(1))
    expect(createInvestmentsFromRequestsMock.mock.calls[0][0]).toMatchObject({
      funding_method: 'cash',
      request_ids: [10],
      comment: 'На основании заявки №10. №10 — компьютер',
    })
  })
})
