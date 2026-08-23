import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PayrollPage } from './PayrollPage'

const getTenantPayrollSettingsMock = vi.fn()
const updateTenantPayrollSettingsMock = vi.fn()
const getTenantPayrollDocIdFormatMock = vi.fn()
const updateTenantPayrollDocIdFormatMock = vi.fn()
const createPayrollDocumentMock = vi.fn()
const reloadMock = vi.fn()
const successMock = vi.fn()
const errorMock = vi.fn()

vi.mock('../lib/api', () => ({
  getTenantPayrollSettings: (...args: unknown[]) => getTenantPayrollSettingsMock(...args),
  updateTenantPayrollSettings: (...args: unknown[]) => updateTenantPayrollSettingsMock(...args),
  getTenantPayrollDocIdFormat: (...args: unknown[]) => getTenantPayrollDocIdFormatMock(...args),
  updateTenantPayrollDocIdFormat: (...args: unknown[]) => updateTenantPayrollDocIdFormatMock(...args),
  createPayrollDocument: (...args: unknown[]) => createPayrollDocumentMock(...args),
}))

// The document table below the settings/modal sections uses useInfiniteList, which
// goes through fetchCursorListPage. That list-loading behavior is unrelated to this
// file's target components (PayrollSettingsSection / CreatePayrollDocumentModal), so
// it's mocked out directly to keep these tests focused and avoid unrelated network noise.
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

// PayrollSettingsSection and CreatePayrollDocumentModal are not exported from
// PayrollPage.tsx, so both are exercised indirectly through the exported PayrollPage.
describe('PayrollSettingsSection (via PayrollPage)', () => {
  beforeEach(() => {
    getTenantPayrollSettingsMock.mockReset()
    updateTenantPayrollSettingsMock.mockReset()
    getTenantPayrollDocIdFormatMock.mockReset().mockRejectedValue(new Error('doc id format not configured'))
    updateTenantPayrollDocIdFormatMock.mockReset()
    createPayrollDocumentMock.mockReset()
    reloadMock.mockReset()
    successMock.mockReset()
    errorMock.mockReset()
  })

  it('renders the checkbox reflecting the fetched setting', async () => {
    getTenantPayrollSettingsMock.mockResolvedValueOnce({ create_payment_request_on_payroll_accrual: true })
    const { container } = renderPage()

    await waitFor(() => {
      const checkbox = container.querySelector('input[type="checkbox"]') as HTMLInputElement
      expect(checkbox.checked).toBe(true)
    })
  })

  it('calls updateTenantPayrollSettings with the new value when toggled', async () => {
    getTenantPayrollSettingsMock.mockResolvedValueOnce({ create_payment_request_on_payroll_accrual: false })
    updateTenantPayrollSettingsMock.mockResolvedValueOnce({ create_payment_request_on_payroll_accrual: true })
    const { container } = renderPage()

    const checkbox = await waitFor(() => {
      const el = container.querySelector('input[type="checkbox"]') as HTMLInputElement
      expect(el.checked).toBe(false)
      return el
    })

    fireEvent.click(checkbox)

    await waitFor(() => {
      expect(updateTenantPayrollSettingsMock).toHaveBeenCalledWith({ create_payment_request_on_payroll_accrual: true })
    })
  })

  it('reverts the checkbox to its previous value when the update fails', async () => {
    getTenantPayrollSettingsMock.mockResolvedValueOnce({ create_payment_request_on_payroll_accrual: false })
    updateTenantPayrollSettingsMock.mockRejectedValueOnce(new Error('save failed'))
    const { container } = renderPage()

    const checkbox = await waitFor(() => {
      const el = container.querySelector('input[type="checkbox"]') as HTMLInputElement
      expect(el.checked).toBe(false)
      return el
    })

    fireEvent.click(checkbox)

    await waitFor(() => expect(updateTenantPayrollSettingsMock).toHaveBeenCalled())
    await waitFor(() => expect(checkbox.checked).toBe(false))
    expect(errorMock).toHaveBeenCalled()
  })
})

describe('CreatePayrollDocumentModal (via PayrollPage)', () => {
  beforeEach(() => {
    getTenantPayrollSettingsMock.mockReset().mockResolvedValue({ create_payment_request_on_payroll_accrual: false })
    updateTenantPayrollSettingsMock.mockReset()
    getTenantPayrollDocIdFormatMock.mockReset().mockRejectedValue(new Error('doc id format not configured'))
    updateTenantPayrollDocIdFormatMock.mockReset()
    createPayrollDocumentMock.mockReset()
    reloadMock.mockReset()
    successMock.mockReset()
    errorMock.mockReset()
  })

  it('renders with one empty row by default', async () => {
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Создать начисление' }))

    const employeeInputs = await screen.findAllByPlaceholderText('Сотрудник (ФИО)')
    expect(employeeInputs).toHaveLength(1)
  })

  it('adds another row when "Добавить строку" is clicked', async () => {
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Создать начисление' }))
    await screen.findAllByPlaceholderText('Сотрудник (ФИО)')

    fireEvent.click(screen.getByRole('button', { name: /Добавить строку/ }))

    const employeeInputs = await screen.findAllByPlaceholderText('Сотрудник (ФИО)')
    expect(employeeInputs).toHaveLength(2)
  })

  it('shows a validation error and does not submit when a required field is empty', async () => {
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Создать начисление' }))
    await screen.findAllByPlaceholderText('Сотрудник (ФИО)')

    fireEvent.click(screen.getByRole('button', { name: 'Создать' }))

    expect(await screen.findByText('ФИО обязательно')).toBeInTheDocument()
    expect(createPayrollDocumentMock).not.toHaveBeenCalled()
  })

  it('submits valid data with a mapped period range and reloads the list', async () => {
    createPayrollDocumentMock.mockResolvedValueOnce({
      id: 1,
      doc_id: null,
      created_at: '2026-08-23T00:00:00Z',
      total_sum: '500.00',
      lines: [],
    })
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Создать начисление' }))

    fireEvent.change(await screen.findByPlaceholderText('Сотрудник (ФИО)'), { target: { value: 'Иванов Иван' } })
    fireEvent.change(screen.getByPlaceholderText('Вид (Salary / Bonus…)'), { target: { value: 'Salary' } })
    fireEvent.change(screen.getByPlaceholderText('Сумма'), { target: { value: '500' } })

    // antd's RangePicker (rc-picker) only accepts typed input through its mask-aware
    // paste handler when a `format` is configured (the default here) — a plain
    // `fireEvent.change` is a no-op in that case, so the committed value must be
    // simulated via `paste` (which validates + commits the text) followed by `Enter`
    // (which confirms the field and advances/flushes the range value into the Form).
    const [periodStartInput, periodEndInput] = Array.from(
      document.querySelectorAll('.ant-picker-range input'),
    ) as HTMLInputElement[]
    fireEvent.mouseDown(periodStartInput)
    fireEvent.paste(periodStartInput, { clipboardData: { getData: () => '2026-08-01' } })
    fireEvent.keyDown(periodStartInput, { key: 'Enter', code: 'Enter' })
    fireEvent.paste(periodEndInput, { clipboardData: { getData: () => '2026-08-31' } })
    fireEvent.keyDown(periodEndInput, { key: 'Enter', code: 'Enter' })

    fireEvent.click(screen.getByRole('button', { name: 'Создать' }))

    await waitFor(() => {
      expect(createPayrollDocumentMock).toHaveBeenCalledWith({
        lines: [
          {
            employee: 'Иванов Иван',
            item: 'Salary',
            description: undefined,
            sum: 500,
            days_plan: null,
            days_fact: null,
            period_start: '2026-08-01',
            period_end: '2026-08-31',
          },
        ],
      })
    })
    await waitFor(() => expect(reloadMock).toHaveBeenCalled())
  })
})
