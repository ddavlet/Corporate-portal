import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { TgPaymentConfirmPage } from './TgPaymentConfirmPage'

const confirmPaymentViaWebAppMock = vi.fn()
const successMock = vi.fn()
const closeMock = vi.fn()

vi.mock('../../lib/api', () => ({
  confirmPaymentViaWebApp: (...args: unknown[]) => confirmPaymentViaWebAppMock(...args),
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

function renderPage(url: string) {
  window.history.pushState({}, '', url)
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/tg/payment" element={<TgPaymentConfirmPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('TgPaymentConfirmPage', () => {
  beforeEach(() => {
    confirmPaymentViaWebAppMock.mockReset()
    successMock.mockReset()
    closeMock.mockReset()
    mainButtonHandler = null
    mainButtonMock.onClick.mockClear()
    ;(window as Window).Telegram = {
      WebApp: {
        initData: '',
        initDataUnsafe: {},
        ready: vi.fn(),
        close: closeMock,
        MainButton: mainButtonMock,
        HapticFeedback: { impactOccurred: vi.fn() },
      },
    }
  })

  it('submits confirmation with approval_id and expense_id', async () => {
    confirmPaymentViaWebAppMock.mockResolvedValueOnce({ request: { id: 1, status: 'approved' } })
    renderPage('/tg/payment?approval_id=12')

    await waitFor(() => expect(mainButtonHandler).not.toBeNull())

    fireEvent.change(screen.getByPlaceholderText('Например, INV-2026-001'), { target: { value: 'INV-100' } })
    tapMainButton()

    await waitFor(() => {
      expect(confirmPaymentViaWebAppMock).toHaveBeenCalledWith({ approval_id: 12, expense_id: 'INV-100' })
    })
    expect(successMock).toHaveBeenCalled()
    expect(closeMock).toHaveBeenCalled()
  })

  it('shows error when approval id is invalid', async () => {
    renderPage('/tg/payment')
    await waitFor(() => expect(mainButtonHandler).not.toBeNull())

    fireEvent.change(screen.getByPlaceholderText('Например, INV-2026-001'), { target: { value: 'INV-100' } })
    tapMainButton()

    expect(await screen.findByText(/Не найден approval_id/)).toBeInTheDocument()
  })
})
