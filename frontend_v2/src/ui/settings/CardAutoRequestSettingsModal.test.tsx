import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const getMock = vi.fn()
const saveMock = vi.fn()

vi.mock('../../lib/cardAutoRequestApi', () => {
  class CardAutoRequestConfigUnavailableError extends Error {
    reason: 'forbidden' | 'unavailable'
    constructor(reason: 'forbidden' | 'unavailable') {
      super(reason)
      this.reason = reason
    }
  }
  return {
    CardAutoRequestConfigUnavailableError,
    getCardAutoRequestConfig: (...a: unknown[]) => getMock(...a),
    saveCardAutoRequestConfig: (...a: unknown[]) => saveMock(...a),
  }
})

import { CardAutoRequestConfigUnavailableError } from '../../lib/cardAutoRequestApi'
import { CardAutoRequestSettingsModal } from './CardAutoRequestSettingsModal'

const config = {
  wallet_id: 58,
  wallet_label: 'Карта Facebook',
  currency: 'UZS',
  is_enabled: false,
  payment_purpose: '',
  category: '',
  company_payer: '',
  vendor_ref_id: null,
  match_text: 'FACEBK',
  updated_at: null,
  options: {
    payment_purposes: [{ name: 'Реклама', category: 'Маркетинг' }],
    vendors: [{ id: 3, name: 'Meta' }],
    default_company_payer: 'ООО Тест',
  },
}

describe('CardAutoRequestSettingsModal', () => {
  beforeEach(() => {
    getMock.mockReset()
    saveMock.mockReset()
  })

  it('fills fields from loaded config', async () => {
    getMock.mockResolvedValue(config)
    render(<CardAutoRequestSettingsModal walletId={58} onClose={() => {}} />)
    expect(await screen.findByDisplayValue('FACEBK')).toBeInTheDocument()
    expect(getMock).toHaveBeenCalledWith(58)
    expect(screen.getByPlaceholderText('ООО Тест')).toBeInTheDocument()
  })

  it('requires purpose when enabled and does not save', async () => {
    getMock.mockResolvedValue(config)
    render(<CardAutoRequestSettingsModal walletId={58} onClose={() => {}} />)
    await screen.findByDisplayValue('FACEBK')
    fireEvent.click(screen.getByRole('switch'))
    fireEvent.click(screen.getByRole('button', { name: /Сохранить/ }))
    expect(await screen.findByText('Выберите назначение')).toBeInTheDocument()
    expect(saveMock).not.toHaveBeenCalled()
  })

  it('saves dto with entered values', async () => {
    getMock.mockResolvedValue({ ...config, payment_purpose: 'Реклама' })
    saveMock.mockResolvedValue(config)
    const onClose = vi.fn()
    render(<CardAutoRequestSettingsModal walletId={58} onClose={onClose} />)
    await screen.findByDisplayValue('FACEBK')
    fireEvent.click(screen.getByRole('switch'))
    fireEvent.click(screen.getByRole('button', { name: /Сохранить/ }))
    await waitFor(() =>
      expect(saveMock).toHaveBeenCalledWith(58, {
        is_enabled: true,
        payment_purpose: 'Реклама',
        category: '',
        company_payer: '',
        vendor_ref_id: null,
        match_text: 'FACEBK',
      }),
    )
    await waitFor(() => expect(onClose).toHaveBeenCalled())
  })

  it('shows save error text', async () => {
    getMock.mockResolvedValue({ ...config, payment_purpose: 'Реклама' })
    saveMock.mockRejectedValue(new Error('Сервер отказал'))
    render(<CardAutoRequestSettingsModal walletId={58} onClose={() => {}} />)
    await screen.findByDisplayValue('FACEBK')
    fireEvent.click(screen.getByRole('button', { name: /Сохранить/ }))
    expect(await screen.findByText('Сервер отказал')).toBeInTheDocument()
  })

  it('shows fallback when module unavailable', async () => {
    getMock.mockRejectedValue(new CardAutoRequestConfigUnavailableError('unavailable'))
    render(<CardAutoRequestSettingsModal walletId={58} onClose={() => {}} />)
    expect(await screen.findByText('Модуль недоступен')).toBeInTheDocument()
  })

  it('shows admin-only text on 403 and hides form', async () => {
    getMock.mockRejectedValue(new CardAutoRequestConfigUnavailableError('forbidden'))
    render(<CardAutoRequestSettingsModal walletId={58} onClose={() => {}} />)
    expect(
      await screen.findByText('Настройку автозаявок меняет только администратор компании'),
    ).toBeInTheDocument()
    expect(screen.queryByRole('switch')).not.toBeInTheDocument()
  })

  it('shows centered loader while config is loading', () => {
    getMock.mockReturnValue(new Promise(() => {}))
    render(<CardAutoRequestSettingsModal walletId={58} onClose={() => {}} />)
    expect(screen.getByTestId('card-auto-request-loading')).toBeInTheDocument()
  })

  it('explains empty purposes directory in the select', async () => {
    getMock.mockResolvedValue({ ...config, options: { ...config.options, payment_purposes: [] } })
    render(<CardAutoRequestSettingsModal walletId={58} onClose={() => {}} />)
    await screen.findByDisplayValue('FACEBK')
    fireEvent.mouseDown(screen.getAllByRole('combobox')[0])
    expect(await screen.findByText('Справочник назначений пуст')).toBeInTheDocument()
  })
})
