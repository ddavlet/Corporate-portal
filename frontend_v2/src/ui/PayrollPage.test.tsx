import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
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
vi.mock('../lib/useInfiniteList', () => ({
  useInfiniteList: () => ({
    items: [],
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
