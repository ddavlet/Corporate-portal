import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const getMock = vi.fn()
const updateMock = vi.fn()

vi.mock('../../lib/api', () => {
  class ApiError extends Error {
    readonly status: number
    constructor(status: number, message: string) {
      super(message)
      this.status = status
    }
  }
  return {
    ApiError,
    getInvestNotificationConfig: () => getMock(),
    updateInvestNotificationConfig: (...args: unknown[]) => updateMock(...args),
    listTelegramChats: () => Promise.resolve([]),
  }
})

import { ApiError } from '../../lib/api'
import { InvestmentNotificationConfigPage } from './InvestmentNotificationConfigPage'

const config = {
  is_active: true,
  days_before: 3,
  overdue_notify_every_days: 1,
  notify_hour: 9,
  responsible_user_id: 2,
  responsible_user_name: 'Иван Петров',
  telegram_chat_id: null,
  approver_candidates: [{ id: 2, label: 'Иван Петров', username: 'ivan' }],
}

function renderPage() {
  return render(
    <MemoryRouter>
      <InvestmentNotificationConfigPage />
    </MemoryRouter>,
  )
}

describe('InvestmentNotificationConfigPage', () => {
  beforeEach(() => {
    getMock.mockReset().mockResolvedValue(config)
    updateMock.mockReset()
  })

  it('explains a 403 on save instead of the raw server message', async () => {
    updateMock.mockRejectedValue(new ApiError(403, 'You do not have permission to perform this action.'))
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Сохранить' }))
    expect(await screen.findByText(/Недостаточно прав/)).toBeInTheDocument()
    expect(screen.queryByText(/You do not have permission/)).not.toBeInTheDocument()
  })

  it('shows the server message for other save errors', async () => {
    updateMock.mockRejectedValue(new ApiError(400, 'Telegram-группа не найдена.'))
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Сохранить' }))
    await waitFor(() => expect(screen.getByText('Telegram-группа не найдена.')).toBeInTheDocument())
  })
})
