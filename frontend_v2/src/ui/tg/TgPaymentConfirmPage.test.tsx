import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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
    ;(window as Window).Telegram = {
      WebApp: {
        initData: '',
        initDataUnsafe: {},
        ready: vi.fn(),
        close: closeMock,
      },
    }
  })

  it('submits confirmation with approval_id and expense_id', async () => {
    confirmPaymentViaWebAppMock.mockResolvedValueOnce({ request: { id: 1, status: 'approved' } })
    renderPage('/tg/payment?approval_id=12')

    fireEvent.change(screen.getByPlaceholderText('Например, INV-2026-001'), { target: { value: 'INV-100' } })
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить выплату' }))

    await waitFor(() => {
      expect(confirmPaymentViaWebAppMock).toHaveBeenCalledWith({ approval_id: 12, expense_id: 'INV-100' })
    })
    expect(successMock).toHaveBeenCalled()
    expect(closeMock).toHaveBeenCalled()
  })

  it('shows error when approval id is invalid', async () => {
    renderPage('/tg/payment')
    fireEvent.change(screen.getByPlaceholderText('Например, INV-2026-001'), { target: { value: 'INV-100' } })
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить выплату' }))
    expect(await screen.findByText(/Не найден approval_id/)).toBeInTheDocument()
  })
})
