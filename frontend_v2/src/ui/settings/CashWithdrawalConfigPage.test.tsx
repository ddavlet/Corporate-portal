import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const getMock = vi.fn()
const saveMock = vi.fn()

vi.mock('../../lib/cashWithdrawalsApi', () => {
  class CashWithdrawalConfigUnavailableError extends Error {}
  return {
    CashWithdrawalConfigUnavailableError,
    getCashWithdrawalConfig: () => getMock(),
    saveCashWithdrawalConfig: (...args: unknown[]) => saveMock(...args),
  }
})

const warningMock = vi.fn()
const successMock = vi.fn()
vi.mock('antd', async () => {
  const mod = await vi.importActual<typeof import('antd')>('antd')
  return {
    ...mod,
    message: { ...mod.message, warning: (...a: unknown[]) => warningMock(...a), success: (...a: unknown[]) => successMock(...a) },
  }
})

import { CashWithdrawalConfigUnavailableError } from '../../lib/cashWithdrawalsApi'
import { CashWithdrawalConfigPage } from './CashWithdrawalConfigPage'

const config = {
  is_active: true,
  card_telegram_chat_id: 1,
  alert_telegram_chat_id: null,
  alert_after_days: 3,
  alert_repeat_every_days: 1,
  alert_hour: 9,
  confirmer_user_ids: [2, 3],
  alert_recipient_user_ids: [2],
  rules: [{ payment_type: 'Перечисление', payment_purpose: 'Снятие наличных с банка', wallet_id: 13 }],
  options: {
    users: [
      { id: 2, label: 'Иван Петров', has_telegram: true },
      { id: 3, label: 'Мария Сидорова', has_telegram: false },
    ],
    telegram_chats: [{ id: 1, name: 'Касса Aqua' }],
    wallets: [{ id: 13, label: 'Основная касса', currency: 'UZS' }],
    payment_purposes: [{ payment_type: 'Перечисление', purposes: ['Снятие наличных с банка'] }],
  },
}

function renderPage() {
  return render(
    <MemoryRouter>
      <CashWithdrawalConfigPage />
    </MemoryRouter>,
  )
}

describe('CashWithdrawalConfigPage', () => {
  beforeEach(() => {
    getMock.mockReset().mockResolvedValue(config)
    saveMock.mockReset().mockResolvedValue(config)
    warningMock.mockReset()
    successMock.mockReset()
  })

  it('renders loaded rules and flags users without Telegram', async () => {
    renderPage()
    expect(await screen.findByText('Снятие наличных с банка')).toBeInTheDocument()
    expect(screen.getByText(/Мария Сидорова: нет Telegram/)).toBeInTheDocument()
  })

  it('saves the loaded config unchanged', async () => {
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Сохранить' }))
    await waitFor(() => expect(saveMock).toHaveBeenCalledTimes(1))
    const { options: _options, ...expected } = config
    expect(saveMock).toHaveBeenCalledWith(expected)
    expect(successMock).toHaveBeenCalled()
  })

  it('does not save an incomplete new rule', async () => {
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Добавить правило/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => expect(warningMock).toHaveBeenCalled())
    expect(saveMock).not.toHaveBeenCalled()
  })

  it('shows a fallback when the setting is unavailable', async () => {
    getMock.mockRejectedValue(new CashWithdrawalConfigUnavailableError('Настройка недоступна'))
    renderPage()
    expect(await screen.findByText('Настройка недоступна')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Сохранить' })).toBeNull()
  })
})
