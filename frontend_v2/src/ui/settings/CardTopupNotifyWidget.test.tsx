import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const getMock = vi.fn()
const saveMock = vi.fn()

vi.mock('../../lib/cashDeskApi', () => {
  class CashDeskConfigUnavailableError extends Error {}
  return {
    CashDeskConfigUnavailableError,
    getCardTopupNotifyConfig: () => getMock(),
    saveCardTopupNotifyConfig: (...args: unknown[]) => saveMock(...args),
  }
})

import { CashDeskConfigUnavailableError } from '../../lib/cashDeskApi'
import { CardTopupNotifyWidget } from './CardTopupNotifyWidget'

const config = {
  is_active: false,
  recipient_ids: [18],
  available_users: [
    { id: 18, name: 'Илхом Уктамов', has_telegram: true },
    { id: 20, name: 'Без Телеграма', has_telegram: false },
  ],
}

describe('CardTopupNotifyWidget', () => {
  beforeEach(() => {
    getMock.mockReset()
    saveMock.mockReset()
  })

  it('shows title, hint and selected recipients', async () => {
    getMock.mockResolvedValue(config)
    render(<CardTopupNotifyWidget />)
    expect(await screen.findByText('Пополнение корпоративной карты')).toBeInTheDocument()
    expect(screen.getByText(/Личное сообщение выбранным людям/)).toBeInTheDocument()
    expect(screen.getByText('Илхом Уктамов')).toBeInTheDocument()
  })

  it('marks users without Telegram in options', async () => {
    getMock.mockResolvedValue({ ...config, recipient_ids: [20] })
    render(<CardTopupNotifyWidget />)
    expect(await screen.findByText('Без Телеграма (нет Telegram)')).toBeInTheDocument()
  })

  it('toggles and saves config', async () => {
    getMock.mockResolvedValue(config)
    saveMock.mockResolvedValue({ ...config, is_active: true })
    render(<CardTopupNotifyWidget />)
    await screen.findByText('Включено')
    fireEvent.click(screen.getByRole('switch'))
    fireEvent.click(screen.getByRole('button', { name: /Сохранить/ }))
    await waitFor(() => expect(saveMock).toHaveBeenCalledWith({ is_active: true, recipient_ids: [18] }))
  })

  it('shows save error', async () => {
    getMock.mockResolvedValue(config)
    saveMock.mockRejectedValue(new Error('Выберите хотя бы одного получателя.'))
    render(<CardTopupNotifyWidget />)
    await screen.findByText('Включено')
    fireEvent.click(screen.getByRole('button', { name: /Сохранить/ }))
    expect(await screen.findByText('Выберите хотя бы одного получателя.')).toBeInTheDocument()
  })

  it('shows load error', async () => {
    getMock.mockRejectedValue(new Error('Ошибка сервера (500)'))
    render(<CardTopupNotifyWidget />)
    expect(await screen.findByText('Ошибка сервера (500)')).toBeInTheDocument()
  })

  it('hides itself when the API is unavailable', async () => {
    getMock.mockRejectedValue(new CashDeskConfigUnavailableError('Настройка недоступна'))
    const { container } = render(<CardTopupNotifyWidget />)
    await waitFor(() => expect(getMock).toHaveBeenCalled())
    await waitFor(() => expect(container).toBeEmptyDOMElement())
    expect(screen.queryByText('Пополнение корпоративной карты')).not.toBeInTheDocument()
  })
})
