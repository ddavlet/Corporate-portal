import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { TgCashRegisterTransferPage } from './TgCashRegisterTransferPage'
import type { CashRegisterDto } from '../../lib/api'

const getCashRegistersMock = vi.fn()
const getSettingsAccessMock = vi.fn()
const createPortalRequestMock = vi.fn()
const submitRequestForApprovalMock = vi.fn()

vi.mock('../../lib/api', () => ({
  getCashRegisters: (...args: unknown[]) => getCashRegistersMock(...args),
  getSettingsAccess: (...args: unknown[]) => getSettingsAccessMock(...args),
  createPortalRequest: (...args: unknown[]) => createPortalRequestMock(...args),
  submitRequestForApproval: (...args: unknown[]) => submitRequestForApprovalMock(...args),
}))

// Captures the handler registered by useTgMainButton so tests can simulate a tap.
let mainButtonHandler: (() => void) | null = null
const mainButtonMock = {
  onClick: vi.fn((fn: () => void) => { mainButtonHandler = fn }),
  offClick: vi.fn(),
  show: vi.fn(),
  hide: vi.fn(),
  showProgress: vi.fn(),
  hideProgress: vi.fn(),
  disable: vi.fn(),
  enable: vi.fn(),
  setText: vi.fn(),
}

function tapMainButton() {
  act(() => { mainButtonHandler?.() })
}

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

function selectOption(placeholder: string, optionText: string) {
  fireEvent.mouseDown(screen.getByText(placeholder))
  return screen.findAllByText(optionText)
}

async function renderReadyPage() {
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
  render(
    <MemoryRouter initialEntries={['/tg/cash/transfer']}>
      <Routes>
        <Route path="/tg/cash/transfer" element={<TgCashRegisterTransferPage />} />
        <Route path="/tg/cash" element={<div>Касса-лендинг</div>} />
      </Routes>
    </MemoryRouter>,
  )
  await screen.findByText('Касса-источник')
  await waitFor(() => expect(mainButtonHandler).not.toBeNull())
}

describe('TgCashRegisterTransferPage', () => {
  beforeEach(() => {
    getCashRegistersMock.mockReset()
    getSettingsAccessMock.mockReset()
    createPortalRequestMock.mockReset()
    submitRequestForApprovalMock.mockReset()
    mainButtonHandler = null
    mainButtonMock.onClick.mockClear()
    ;(window as Window).Telegram = {
      WebApp: {
        initData: '',
        initDataUnsafe: {},
        ready: vi.fn(),
        close: vi.fn(),
        MainButton: mainButtonMock,
        HapticFeedback: { impactOccurred: vi.fn(), notificationOccurred: vi.fn(), selectionChanged: vi.fn() },
      },
    }
  })

  it('loads active cash registers into the from/to selects', async () => {
    await renderReadyPage()

    fireEvent.mouseDown(screen.getByText('Касса-источник'))
    expect((await screen.findAllByText('Касса А')).length).toBeGreaterThan(0)
    expect((await screen.findAllByText('Касса Б')).length).toBeGreaterThan(0)
  })

  it('creates a transfer request and submits it for approval on main button tap', async () => {
    await renderReadyPage()

    const fromOptions = await selectOption('Касса-источник', 'Касса А')
    fireEvent.click(fromOptions[fromOptions.length - 1])
    const toOptions = await selectOption('Касса-назначение', 'Касса Б')
    fireEvent.click(toOptions[toOptions.length - 1])
    fireEvent.change(screen.getByLabelText('Сумма'), { target: { value: '50000' } })

    createPortalRequestMock.mockResolvedValueOnce({ id: 777 })
    submitRequestForApprovalMock.mockResolvedValueOnce({ status: '1' })

    tapMainButton()

    await waitFor(() => {
      expect(createPortalRequestMock).toHaveBeenCalledWith(
        expect.objectContaining({
          payment_type: 'Наличные',
          payment_purpose: 'Перевод между кассами',
          amount: 50000,
          currency: 'UZS',
          status: 'DRAFT',
          requester: 555,
          wallet_ref: 101,
        }),
      )
    })
    await waitFor(() => expect(submitRequestForApprovalMock).toHaveBeenCalledWith(777))
    await screen.findByText('Касса-лендинг')
  })

  it('keeps the created draft and shows an error when submit-for-approval fails', async () => {
    await renderReadyPage()

    const fromOptions = await selectOption('Касса-источник', 'Касса А')
    fireEvent.click(fromOptions[fromOptions.length - 1])
    const toOptions = await selectOption('Касса-назначение', 'Касса Б')
    fireEvent.click(toOptions[toOptions.length - 1])
    fireEvent.change(screen.getByLabelText('Сумма'), { target: { value: '1000' } })

    createPortalRequestMock.mockResolvedValueOnce({ id: 888 })
    submitRequestForApprovalMock.mockRejectedValueOnce(new Error('Payment purpose is not allowed'))

    tapMainButton()

    expect(await screen.findByText(/888/)).toBeInTheDocument()
  })
})
