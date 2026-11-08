import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const listMock = vi.fn()
const optionsMock = vi.fn()
const createMock = vi.fn()
const updateMock = vi.fn()
const deleteMock = vi.fn()

vi.mock('../../lib/dividendPayoutsApi', () => {
  class DividendPayoutsApiError extends Error {
    status: number
    fieldErrors: Record<string, string[]>
    constructor(status: number, message: string, fieldErrors: Record<string, string[]> = {}) {
      super(message)
      this.status = status
      this.fieldErrors = fieldErrors
    }
  }
  return {
    DividendPayoutsApiError,
    listDividendPayoutRules: () => listMock(),
    getDividendPayoutOptions: () => optionsMock(),
    createDividendPayoutRule: (...args: unknown[]) => createMock(...args),
    updateDividendPayoutRule: (...args: unknown[]) => updateMock(...args),
    deleteDividendPayoutRule: (...args: unknown[]) => deleteMock(...args),
  }
})

import { DividendPayoutsApiError } from '../../lib/dividendPayoutsApi'
import { DividendPayoutRulesPage } from './DividendPayoutRulesPage'

const options = {
  return_types: [
    { value: 'дивиденды', label: 'Дивиденды' },
    { value: 'проценты', label: 'Проценты' },
  ],
  recipients: [
    { value: 'инвестор', label: 'Учредитель (инвестор)' },
    { value: 'партнер', label: 'Партнёр' },
  ],
  payment_purposes: ['Выплата дивидендов', 'Аренда'],
}

const rule = {
  id: 1,
  payment_purpose: 'Выплата дивидендов',
  return_type: 'дивиденды',
  recipient: 'инвестор',
  is_active: true,
}

function renderPage() {
  return render(
    <MemoryRouter>
      <DividendPayoutRulesPage />
    </MemoryRouter>,
  )
}

describe('DividendPayoutRulesPage', () => {
  beforeEach(() => {
    listMock.mockReset()
    optionsMock.mockReset()
    createMock.mockReset()
    updateMock.mockReset()
    deleteMock.mockReset()
  })

  it('renders existing rules', async () => {
    listMock.mockResolvedValue([rule])
    optionsMock.mockResolvedValue(options)
    renderPage()
    await screen.findByDisplayValue('Выплата дивидендов')
    const table = within(screen.getByRole('table'))
    expect(table.getByText('Дивиденды')).toBeInTheDocument()
    expect(table.getByText('Учредитель (инвестор)')).toBeInTheDocument()
    expect(table.getByRole('switch')).toBeChecked()
  })

  it('adds a rule via POST with the form values', async () => {
    listMock.mockResolvedValue([])
    optionsMock.mockResolvedValue(options)
    createMock.mockResolvedValue({ ...rule, id: 2, payment_purpose: 'Аренда' })
    renderPage()
    await screen.findByText('Правил пока нет')

    fireEvent.click(screen.getByRole('button', { name: /Добавить правило/ }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.change(within(dialog).getByRole('combobox', { name: 'Назначение платежа' }), {
      target: { value: 'Аренда' },
    })
    fireEvent.click(within(dialog).getByRole('button', { name: /Сохранить/ }))

    await waitFor(() =>
      expect(createMock).toHaveBeenCalledWith({
        payment_purpose: 'Аренда',
        return_type: 'дивиденды',
        recipient: 'инвестор',
        is_active: true,
      }),
    )
    expect(await within(screen.getByRole('table')).findByDisplayValue('Аренда')).toBeInTheDocument()
  })

  it('shows server field errors on create', async () => {
    listMock.mockResolvedValue([])
    optionsMock.mockResolvedValue(options)
    createMock.mockRejectedValue(
      new DividendPayoutsApiError(400, 'Правило уже есть', { payment_purpose: ['Правило для этого назначения уже есть'] }),
    )
    renderPage()
    await screen.findByText('Правил пока нет')

    fireEvent.click(screen.getByRole('button', { name: /Добавить правило/ }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.change(within(dialog).getByRole('combobox', { name: 'Назначение платежа' }), {
      target: { value: 'Аренда' },
    })
    fireEvent.click(within(dialog).getByRole('button', { name: /Сохранить/ }))

    expect(await within(dialog).findByText('Правило для этого назначения уже есть')).toBeInTheDocument()
  })

  it('shows a fallback when the module is unavailable (404)', async () => {
    listMock.mockRejectedValue(new DividendPayoutsApiError(404, 'Not found'))
    optionsMock.mockRejectedValue(new DividendPayoutsApiError(404, 'Not found'))
    renderPage()
    expect(await screen.findByText('Модуль правил дивидендов недоступен')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Добавить правило/ })).not.toBeInTheDocument()
  })
})
