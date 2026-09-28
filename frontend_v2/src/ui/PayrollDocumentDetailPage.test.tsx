import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom'
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

// Test-only helper that lets a test trigger client-side navigation to another /payroll/:id
// while the route stays mounted — same navigation path as "Скопировать" or clicking a row
// in the list — without unmounting PayrollDocumentDetailPage, so it exercises the
// stale-response guard in reload().
function NavigateTo({ to }: { to: string }) {
  const navigate = useNavigate()
  return (
    <button type="button" onClick={() => navigate(to)}>
      {`go-to:${to}`}
    </button>
  )
}

function renderPageWithNav(initialId = '1') {
  return render(
    <MemoryRouter initialEntries={[`/payroll/${initialId}`]}>
      <NavigateTo to="/payroll/2" />
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

  it('ignores a stale document response for a previous id after navigating to a new one', async () => {
    let resolveDoc1: ((doc: PayrollDocumentDetailDto) => void) | null = null
    const doc1Promise = new Promise<PayrollDocumentDetailDto>((resolve) => {
      resolveDoc1 = resolve
    })
    getPayrollDocumentMock.mockImplementation((requestedId: string) => {
      if (requestedId === '1') return doc1Promise
      if (requestedId === '2') return Promise.resolve(baseDoc({ id: 2, label: 'Doc-B' }))
      throw new Error(`unexpected id ${requestedId}`)
    })

    renderPageWithNav('1')

    // Initial request for id=1 is in flight (deliberately not resolved yet).
    await waitFor(() => expect(getPayrollDocumentMock).toHaveBeenCalledWith('1'))

    // Navigate to id=2 without unmounting the page (route element stays mounted).
    fireEvent.click(screen.getByText('go-to:/payroll/2'))
    await waitFor(() => expect(getPayrollDocumentMock).toHaveBeenCalledWith('2'))
    expect(await screen.findByText('Начисление ЗП Doc-B')).toBeInTheDocument()

    // The slow id=1 response now lands — it must be ignored, not overwrite id=2's data.
    await act(async () => {
      resolveDoc1?.(baseDoc({ id: 1, label: 'Doc-A' }))
      await Promise.resolve()
    })

    expect(screen.getByText('Начисление ЗП Doc-B')).toBeInTheDocument()
    expect(screen.queryByText('Начисление ЗП Doc-A')).not.toBeInTheDocument()
  })
})
