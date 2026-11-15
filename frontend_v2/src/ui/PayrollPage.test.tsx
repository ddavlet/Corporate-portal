import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PayrollPage } from './PayrollPage'

const listEmployeesMock = vi.fn()
const reloadMock = vi.fn()
const successMock = vi.fn()
const errorMock = vi.fn()

vi.mock('../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../lib/api')>('../lib/api')
  return {
    ...actual,
    listEmployees: (...args: unknown[]) => listEmployeesMock(...args),
    createEmployee: vi.fn(),
    createPayrollDraft: vi.fn(),
    updatePayrollDraft: vi.fn(),
  }
})

// The document table below the settings/modal sections uses useInfiniteList, which
// goes through fetchCursorListPage. That list-loading behavior is unrelated to this
// file's target components (filters / PayrollDocumentFormModal), so it's mocked out
// directly to keep these tests focused and avoid unrelated network noise.
let listItems: unknown[] = []
let cardReviewCount = 0

vi.mock('../lib/usePayrollCardAttention', () => ({
  usePayrollCardAttention: () => ({ data: null, loading: false, error: null, count: cardReviewCount, refresh: vi.fn() }),
}))

vi.mock('../lib/useInfiniteList', () => ({
  useInfiniteList: () => ({
    items: listItems,
    loading: false,
    error: null,
    hasMore: false,
    loadingMore: false,
    sentinelRef: { current: null },
    reload: reloadMock,
  }),
}))

vi.mock('antd', async () => {
  const mod = await vi.importActual<typeof import('antd')>('antd')
  return {
    ...mod,
    message: {
      ...mod.message,
      success: (...args: unknown[]) => successMock(...args),
      error: (...args: unknown[]) => errorMock(...args),
    },
  }
})

function renderPage() {
  return render(
    <MemoryRouter>
      <PayrollPage />
    </MemoryRouter>,
  )
}

// PayrollDocumentFormModal is not exported from PayrollPage.tsx, so it's exercised
// indirectly through the exported PayrollPage.
describe('PayrollDocumentFormModal (via PayrollPage)', () => {
  beforeEach(() => {
    listEmployeesMock.mockReset()
    listEmployeesMock.mockResolvedValue([])
    reloadMock.mockReset()
    successMock.mockReset()
    errorMock.mockReset()
  })

  it('opens the draft form modal when "Создать начисление" is clicked', async () => {
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Создать начисление' }))

    expect(await screen.findByText('Новое начисление')).toBeInTheDocument()
  })
})

describe('PayrollPage card payouts', () => {
  beforeEach(() => {
    listItems = []
    cardReviewCount = 0
  })

  it('shows «Требует разбора: N» as a link to the review page when something needs a decision', () => {
    cardReviewCount = 3
    render(
      <MemoryRouter initialEntries={['/payroll']}>
        <Routes>
          <Route path="/payroll" element={<PayrollPage />} />
          <Route path="/payroll/card-review" element={<div>Экран разбора</div>} />
        </Routes>
      </MemoryRouter>,
    )
    const link = screen.getByRole('link', { name: 'Требует разбора: 3' })
    // A real href: the review opens in a new tab with Ctrl/Cmd or the middle button.
    expect(link).toHaveAttribute('href', '/payroll/card-review')
    fireEvent.click(link)
    expect(screen.getByText('Экран разбора')).toBeInTheDocument()
  })

  it('hides the review link at zero or without access', () => {
    renderPage()
    expect(screen.queryByRole('link', { name: /Требует разбора/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Требует разбора/ })).not.toBeInTheDocument()
  })

  it('shows the overpaid tag and the cash/card split in the list row', () => {
    listItems = [
      {
        id: 1,
        doc_id: null,
        label: 'ЗП-1',
        created_at: '2026-10-01T00:00:00Z',
        total_sum: '3000000.00',
        lines_count: 1,
        status: 'closed',
        period_month: '2026-09-01',
        kind: 'salary',
        paid_total: '1500000.00',
        card_paid_total: '2000000.00',
        overpaid_total: '500000.00',
      },
    ]
    renderPage()
    expect(screen.getByText(/Переплата 500\s000,00/)).toBeInTheDocument()
    expect(screen.getByText(/касса 1\s500\s000,00 · карта 2\s000\s000,00/)).toBeInTheDocument()
  })

  it('has no overpaid tag for a row without card money', () => {
    listItems = [
      {
        id: 1,
        doc_id: null,
        label: 'ЗП-1',
        created_at: '2026-10-01T00:00:00Z',
        total_sum: '3000000.00',
        lines_count: 1,
        status: 'accepted',
        period_month: '2026-09-01',
        kind: 'salary',
        paid_total: '1000000.00',
        card_paid_total: '0.00',
        overpaid_total: '0.00',
      },
    ]
    renderPage()
    expect(screen.getByText('ЗП-1')).toBeInTheDocument()
    expect(screen.queryByText(/Переплата/)).not.toBeInTheDocument()
  })
})
