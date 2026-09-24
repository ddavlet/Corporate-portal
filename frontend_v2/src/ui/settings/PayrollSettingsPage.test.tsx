import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PayrollSettingsPage } from './PayrollSettingsPage'

const getTenantPayrollSettingsMock = vi.fn()
const updateTenantPayrollSettingsMock = vi.fn()
const getTenantPayrollDocIdFormatMock = vi.fn()
const updateTenantPayrollDocIdFormatMock = vi.fn()

vi.mock('../../lib/api', () => ({
  getTenantPayrollSettings: (...args: unknown[]) => getTenantPayrollSettingsMock(...args),
  updateTenantPayrollSettings: (...args: unknown[]) => updateTenantPayrollSettingsMock(...args),
  getTenantPayrollDocIdFormat: (...args: unknown[]) => getTenantPayrollDocIdFormatMock(...args),
  updateTenantPayrollDocIdFormat: (...args: unknown[]) => updateTenantPayrollDocIdFormatMock(...args),
}))

const successMock = vi.fn()
const errorMock = vi.fn()

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
  return render(<PayrollSettingsPage />)
}

describe('PayrollSettingsSection (via PayrollSettingsPage)', () => {
  beforeEach(() => {
    getTenantPayrollSettingsMock.mockReset()
    updateTenantPayrollSettingsMock.mockReset()
    getTenantPayrollDocIdFormatMock.mockReset().mockRejectedValue(new Error('doc id format not configured'))
    updateTenantPayrollDocIdFormatMock.mockReset()
    successMock.mockReset()
    errorMock.mockReset()
  })

  it('renders the checkbox reflecting the fetched setting', async () => {
    getTenantPayrollSettingsMock.mockResolvedValueOnce({
      create_payment_request_on_payroll_accrual: true,
      payroll_payout_mode: 'legacy',
    })
    const { container } = renderPage()

    await waitFor(() => {
      const checkbox = container.querySelector('input[type="checkbox"]') as HTMLInputElement
      expect(checkbox.checked).toBe(true)
    })
  })

  it('calls updateTenantPayrollSettings with the new value when toggled', async () => {
    getTenantPayrollSettingsMock.mockResolvedValueOnce({
      create_payment_request_on_payroll_accrual: false,
      payroll_payout_mode: 'legacy',
    })
    updateTenantPayrollSettingsMock.mockResolvedValueOnce({
      create_payment_request_on_payroll_accrual: true,
      payroll_payout_mode: 'legacy',
    })
    const { container } = renderPage()

    const checkbox = await waitFor(() => {
      const el = container.querySelector('input[type="checkbox"]') as HTMLInputElement
      expect(el.checked).toBe(false)
      return el
    })

    fireEvent.click(checkbox)

    await waitFor(() => {
      expect(updateTenantPayrollSettingsMock).toHaveBeenCalledWith({
        create_payment_request_on_payroll_accrual: true,
        payroll_payout_mode: 'legacy',
      })
    })
  })

  it('reverts the checkbox to its previous value when the update fails', async () => {
    getTenantPayrollSettingsMock.mockResolvedValueOnce({
      create_payment_request_on_payroll_accrual: false,
      payroll_payout_mode: 'legacy',
    })
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

  it('defaults the payout mode to "legacy" when missing from the response', async () => {
    getTenantPayrollSettingsMock.mockResolvedValueOnce({ create_payment_request_on_payroll_accrual: false })
    renderPage()

    await waitFor(() => {
      const legacyRadio = screen.getByRole('radio', { name: /Как раньше/i }) as HTMLInputElement
      expect(legacyRadio.checked).toBe(true)
    })
  })

  it('sends payroll_payout_mode: "portal" when the portal mode is selected and saved', async () => {
    getTenantPayrollSettingsMock.mockResolvedValueOnce({
      create_payment_request_on_payroll_accrual: false,
      payroll_payout_mode: 'legacy',
    })
    updateTenantPayrollSettingsMock.mockResolvedValueOnce({
      create_payment_request_on_payroll_accrual: false,
      payroll_payout_mode: 'portal',
    })
    renderPage()

    const portalRadio = await waitFor(() => screen.getByRole('radio', { name: /Через портал/i }))

    fireEvent.click(portalRadio)

    await waitFor(() => {
      expect(updateTenantPayrollSettingsMock).toHaveBeenCalledWith({
        create_payment_request_on_payroll_accrual: false,
        payroll_payout_mode: 'portal',
      })
    })
  })
})
