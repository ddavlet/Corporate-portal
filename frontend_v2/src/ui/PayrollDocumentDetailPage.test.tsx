import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PayrollDocumentDetailPage } from './PayrollDocumentDetailPage'
import type { PayrollDocumentDetailDto, PayrollPayoutStateDto } from '../lib/api'

const getPayrollDocumentMock = vi.fn()
const getPayrollPayoutStateMock = vi.fn()

vi.mock('../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../lib/api')>('../lib/api')
  return {
    ...actual,
    getPayrollDocument: (...args: unknown[]) => getPayrollDocumentMock(...args),
    getPayrollPayoutState: (...args: unknown[]) => getPayrollPayoutStateMock(...args),
  }
})

function baseDoc(overrides: Partial<PayrollDocumentDetailDto> = {}): PayrollDocumentDetailDto {
  return {
    id: 1,
    doc_id: null,
    label: 'ЗП-1',
    created_at: '2026-09-01T00:00:00Z',
    total_sum: '1000.00',
    status: 'draft',
    source: 'portal',
    payout_mode: 'portal',
    period_month: '2026-09-01',
    kind: 'salary',
    closed_underpaid_at: null,
    close_comment: '',
    current_request: null,
    paid_total: '0.00',
    remaining_total: '1000.00',
    lines: [],
    ...overrides,
  }
}

function basePayoutState(overrides: Partial<PayrollPayoutStateDto> = {}): PayrollPayoutStateDto {
  return {
    can_pay: true,
    reason: null,
    employees: [],
    accrued_total: '1000.00',
    paid_total: '0.00',
    remaining_total: '1000.00',
    expenses: [],
    request: null,
    ...overrides,
  }
}

function renderPage(id = '1') {
  return render(
    <MemoryRouter initialEntries={[`/payroll/${id}`]}>
      <Routes>
        <Route path="/payroll/:id" element={<PayrollDocumentDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('PayrollDocumentDetailPage', () => {
  beforeEach(() => {
    getPayrollDocumentMock.mockReset()
    getPayrollPayoutStateMock.mockReset()
  })

  it('shows "Принять" and "Редактировать" but not "Создать расход" for a draft portal document', async () => {
    getPayrollDocumentMock.mockResolvedValue(baseDoc())
    renderPage()

    expect(await screen.findByRole('button', { name: 'Принять' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Редактировать' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Создать расход' })).not.toBeInTheDocument()
    expect(getPayrollPayoutStateMock).not.toHaveBeenCalled()
  })

  it('shows "Создать расход" for an accepted portal document with can_pay=true', async () => {
    getPayrollDocumentMock.mockResolvedValue(baseDoc({ status: 'accepted' }))
    getPayrollPayoutStateMock.mockResolvedValue(basePayoutState({ can_pay: true }))
    renderPage()

    expect(await screen.findByRole('button', { name: 'Создать расход' })).toBeInTheDocument()
    await waitFor(() => expect(getPayrollPayoutStateMock).toHaveBeenCalledWith(1))
  })

  it('shows the reason text instead of "Создать расход" when can_pay=false', async () => {
    getPayrollDocumentMock.mockResolvedValue(baseDoc({ status: 'accepted' }))
    getPayrollPayoutStateMock.mockResolvedValue(
      basePayoutState({ can_pay: false, reason: 'Нет одобренной заявки на выплату' }),
    )
    renderPage()

    expect(await screen.findByText('Нет одобренной заявки на выплату')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Создать расход' })).not.toBeInTheDocument()
  })
})
