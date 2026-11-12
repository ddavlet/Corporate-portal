import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { message } from 'antd'
import dayjs from 'dayjs'
import timezone from 'dayjs/plugin/timezone'
import utc from 'dayjs/plugin/utc'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ReturnsTab } from './ReturnsTab'

dayjs.extend(utc)
dayjs.extend(timezone)

const createInvestReturnMock = vi.fn()

vi.mock('../../lib/api', () => ({
  createInvestReturn: (...args: unknown[]) => createInvestReturnMock(...args),
}))

vi.mock('../admin/AdminEditRecordButton', () => ({ AdminEditRecordButton: () => null }))
vi.mock('./InvestmentRecordDetailModal', () => ({ InvestmentRecordDetailModal: () => null }))

const TYPE_OPTIONS = [
  { value: 'return_of_funds', label: 'Возврат средств' },
  { value: 'dividend', label: 'Дивиденды' },
]

function renderTab(
  over: {
    returnTypeSelectOptions?: { value: string; label: string }[]
    onCreated?: () => Promise<void> | void
  } = {},
) {
  const onCreated = over.onCreated ?? vi.fn().mockResolvedValue(undefined)
  render(
    <MemoryRouter>
      <ReturnsTab
        loading={false}
        rows={[]}
        returnTypeSelectOptions={over.returnTypeSelectOptions ?? TYPE_OPTIONS}
        onCreated={onCreated}
      />
    </MemoryRouter>,
  )
  return { onCreated }
}

async function openCreateModal() {
  // Точное имя: «Создать первую выплату» в пустом состоянии таблицы — другая кнопка.
  fireEvent.click(screen.getByRole('button', { name: 'Создать выплату' }))
  await waitFor(() => expect(document.getElementById('sum')).not.toBeNull())
}

function inputValue(id: string): string | null {
  const el = document.getElementById(id) as HTMLInputElement | null
  return el ? el.value : null
}

function selectedText(id: string): string | null {
  const item = document.getElementById(id)?.closest('.ant-select')?.querySelector('.ant-select-selection-item')
  return item ? (item.textContent ?? '') : null
}

function okButton(): HTMLButtonElement {
  return document.querySelector('.ant-modal-footer .ant-btn-primary') as HTMLButtonElement
}

describe('ReturnsTab: модалка «Создать выплату» (характеризация текущего поведения)', () => {
  beforeEach(() => {
    createInvestReturnMock.mockReset()
    // 25 ноября 2026, 12:00 по Ташкенту: «сегодня» одинаково в любом часовом поясе раннера.
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-25T07:00:00Z'))
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('opens with defaults: today, current accrual month, USD, first type, investor', async () => {
    renderTab()
    await openCreateModal()

    expect(document.querySelector('.ant-modal-title')?.textContent).toBe('Создать выплату')
    expect(inputValue('date')).toBe('25.11.2026')
    expect(inputValue('billing_date')).toBe('11.2026')
    expect(selectedText('currency')).toBe('USD')
    expect(selectedText('type')).toBe('Возврат средств')
    expect(selectedText('recipient')).toBe('Инвестор')
    expect(inputValue('sum')).toBe('')
    expect(screen.getByText('Сумма (USD)')).toBeTruthy()
  })

  it('falls back to the type «дивиденды» when there are no type options', async () => {
    renderTab({ returnTypeSelectOptions: [] })
    await openCreateModal()

    expect(selectedText('type')).toBe('дивиденды')

    fireEvent.change(document.getElementById('sum') as HTMLInputElement, { target: { value: '1500' } })
    createInvestReturnMock.mockResolvedValue({})
    fireEvent.click(okButton())
    await waitFor(() => expect(createInvestReturnMock).toHaveBeenCalledTimes(1))
    expect(createInvestReturnMock.mock.calls[0][0]).toMatchObject({ type: 'дивиденды' })
  })

  it('sends one request with the exact payload, reports success and calls onCreated', async () => {
    createInvestReturnMock.mockResolvedValue({})
    const successSpy = vi.spyOn(message, 'success').mockImplementation(() => undefined as never)
    const errorSpy = vi.spyOn(message, 'error').mockImplementation(() => undefined as never)
    const { onCreated } = renderTab()
    await openCreateModal()

    fireEvent.change(document.getElementById('sum') as HTMLInputElement, { target: { value: '1500' } })
    fireEvent.click(okButton())

    await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1))
    expect(createInvestReturnMock).toHaveBeenCalledTimes(1)
    expect(createInvestReturnMock.mock.calls[0][0]).toEqual({
      date: '2026-11-25',
      billing_date: '2026-11-01',
      sum: '1500',
      currency: 'USD',
      type: 'return_of_funds',
      recipient: 'инвестор',
      comment: '',
    })
    expect(successSpy).toHaveBeenCalledWith('Выплата создана и отправлена на согласование')
    expect(errorSpy).not.toHaveBeenCalled()
  })

  it('does not send a request without a sum and shows the validation text', async () => {
    const successSpy = vi.spyOn(message, 'success').mockImplementation(() => undefined as never)
    const { onCreated } = renderTab()
    await openCreateModal()

    fireEvent.click(okButton())

    expect(await screen.findByText('Укажите сумму')).toBeTruthy()
    expect(createInvestReturnMock).not.toHaveBeenCalled()
    expect(onCreated).not.toHaveBeenCalled()
    expect(successSpy).not.toHaveBeenCalled()
  })

  it('shows the server error and keeps the modal open when creation fails', async () => {
    createInvestReturnMock.mockRejectedValue(new Error('Сервер отклонил выплату'))
    const successSpy = vi.spyOn(message, 'success').mockImplementation(() => undefined as never)
    const errorSpy = vi.spyOn(message, 'error').mockImplementation(() => undefined as never)
    const { onCreated } = renderTab()
    await openCreateModal()

    fireEvent.change(document.getElementById('sum') as HTMLInputElement, { target: { value: '1500' } })
    fireEvent.click(okButton())

    await waitFor(() => expect(errorSpy).toHaveBeenCalledWith('Сервер отклонил выплату'))
    expect(createInvestReturnMock).toHaveBeenCalledTimes(1)
    expect(successSpy).not.toHaveBeenCalled()
    expect(onCreated).not.toHaveBeenCalled()
    expect(document.querySelector('.ant-modal-title')?.textContent).toBe('Создать выплату')
    expect(document.getElementById('sum')).not.toBeNull()
  })
})
