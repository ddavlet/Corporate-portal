import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { CashRegisterTransferButton } from './CashRegisterTransferButton'
import type { CashRegisterDto } from '../lib/api'

const getCashRegistersMock = vi.fn()
const getSettingsAccessMock = vi.fn()
const createPortalRequestMock = vi.fn()
const submitRequestForApprovalMock = vi.fn()
const successMock = vi.fn()

vi.mock('../lib/api', () => ({
  getCashRegisters: (...args: unknown[]) => getCashRegistersMock(...args),
  getSettingsAccess: (...args: unknown[]) => getSettingsAccessMock(...args),
  createPortalRequest: (...args: unknown[]) => createPortalRequestMock(...args),
  submitRequestForApproval: (...args: unknown[]) => submitRequestForApprovalMock(...args),
}))

vi.mock('antd', async () => {
  const mod = await vi.importActual<typeof import('antd')>('antd')
  return {
    ...mod,
    message: {
      ...mod.message,
      success: (...args: unknown[]) => successMock(...args),
    },
  }
})

const REGISTER_A: CashRegisterDto = {
  id: 1,
  tenant: 1,
  currency: 'UZS',
  name: 'Касса А',
  code: '',
  description: '',
  is_active: true,
  sort_order: 0,
  is_default_for_currency: true,
  wallet_id: 101,
}

const REGISTER_B: CashRegisterDto = {
  id: 2,
  tenant: 1,
  currency: 'UZS',
  name: 'Касса Б',
  code: '',
  description: '',
  is_active: true,
  sort_order: 1,
  is_default_for_currency: false,
  wallet_id: 102,
}

async function openModalWithRegisters() {
  getCashRegistersMock.mockResolvedValueOnce([REGISTER_A, REGISTER_B])
  getSettingsAccessMock.mockResolvedValueOnce({
    can_open_settings: true,
    can_open_admin: true,
    can_manage_tenant_settings: true,
    can_manage_requests_settings: true,
    can_manage_wallet_settings: true,
    roles: ['admin'],
    user_id: 555,
  })
  render(<CashRegisterTransferButton onCreated={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: /Перевести между кассами/ }))
  await screen.findByText('Касса-источник')
}

function selectOption(placeholder: string, optionText: string) {
  fireEvent.mouseDown(screen.getByText(placeholder))
  return screen.findAllByText(optionText)
}

describe('CashRegisterTransferButton', () => {
  beforeEach(() => {
    getCashRegistersMock.mockReset()
    getSettingsAccessMock.mockReset()
    createPortalRequestMock.mockReset()
    submitRequestForApprovalMock.mockReset()
    successMock.mockReset()
  })

  it('opens a modal listing active cash registers on click', async () => {
    await openModalWithRegisters()

    fireEvent.mouseDown(screen.getByText('Касса-источник'))
    expect((await screen.findAllByText('Касса А')).length).toBeGreaterThan(0)
    expect((await screen.findAllByText('Касса Б')).length).toBeGreaterThan(0)
  })

  it('creates a request and submits it for approval on confirm', async () => {
    await openModalWithRegisters()

    const fromOptions = await selectOption('Касса-источник', 'Касса А')
    fireEvent.click(fromOptions[fromOptions.length - 1])

    const toOptions = await selectOption('Касса-назначение', 'Касса Б')
    fireEvent.click(toOptions[toOptions.length - 1])

    fireEvent.change(screen.getByLabelText('Сумма'), { target: { value: '50000' } })

    createPortalRequestMock.mockResolvedValueOnce({ id: 777 })
    submitRequestForApprovalMock.mockResolvedValueOnce({ status: '1' })

    fireEvent.click(screen.getByRole('button', { name: 'Отправить' }))

    await waitFor(() => {
      expect(createPortalRequestMock).toHaveBeenCalledWith(
        expect.objectContaining({
          payment_type: 'Наличные',
          payment_purpose: 'Перевод между кассами',
          amount: 50000,
          currency: 'UZS',
          status: 'DRAFT',
          requester: 555,
        }),
      )
    })
    await waitFor(() => {
      expect(submitRequestForApprovalMock).toHaveBeenCalledWith(777)
    })
    expect(successMock).toHaveBeenCalled()
  })

  it('keeps the created draft and shows an error when submit-for-approval fails', async () => {
    await openModalWithRegisters()

    const fromOptions = await selectOption('Касса-источник', 'Касса А')
    fireEvent.click(fromOptions[fromOptions.length - 1])

    const toOptions = await selectOption('Касса-назначение', 'Касса Б')
    fireEvent.click(toOptions[toOptions.length - 1])

    fireEvent.change(screen.getByLabelText('Сумма'), { target: { value: '1000' } })

    createPortalRequestMock.mockResolvedValueOnce({ id: 888 })
    submitRequestForApprovalMock.mockRejectedValueOnce(new Error('Payment purpose is not allowed'))

    fireEvent.click(screen.getByRole('button', { name: 'Отправить' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('888')
  })
})
