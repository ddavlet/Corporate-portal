import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const getMock = vi.fn()
const saveMock = vi.fn()

vi.mock('../../lib/cashDeskApi', () => {
  class CashDeskConfigUnavailableError extends Error {}
  return {
    CashDeskConfigUnavailableError,
    getCashDeskConfig: () => getMock(),
    saveCashDeskConfig: (...args: unknown[]) => saveMock(...args),
  }
})

import { CashDeskConfigPage } from './CashDeskConfigPage'

const config = {
  is_active: false,
  telegram_chat_id: 7,
  options: { telegram_chats: [{ id: 7, name: 'Касса AQUA' }] },
}

describe('CashDeskConfigPage', () => {
  beforeEach(() => {
    getMock.mockReset()
    saveMock.mockReset()
  })

  it('loads and saves config', async () => {
    getMock.mockResolvedValue(config)
    saveMock.mockResolvedValue({ ...config, is_active: true })
    render(
      <MemoryRouter>
        <CashDeskConfigPage />
      </MemoryRouter>,
    )
    await screen.findByText('Включено')
    fireEvent.click(screen.getByRole('switch'))
    fireEvent.click(screen.getByRole('button', { name: /Сохранить/ }))
    await waitFor(() => expect(saveMock).toHaveBeenCalledWith({ is_active: true, telegram_chat_id: 7 }))
  })
})
