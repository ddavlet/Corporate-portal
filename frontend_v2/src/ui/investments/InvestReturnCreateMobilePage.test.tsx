import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { message } from 'antd'
import dayjs from 'dayjs'
import timezone from 'dayjs/plugin/timezone'
import utc from 'dayjs/plugin/utc'
import { MemoryRouter, Route, Routes, useLocation, useNavigate, type NavigateFunction } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { InvestReturnCreateMobilePage } from './InvestReturnCreateMobilePage'

// main.tsx extends dayjs in the app; the accrual month defaults need .tz() (tashkentTime).
dayjs.extend(utc)
dayjs.extend(timezone)

const api = vi.hoisted(() => ({
  getInvestmentFormConfig: vi.fn(),
  createInvestReturn: vi.fn(),
}))

vi.mock('../../lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/api')>()),
  getInvestmentFormConfig: (...a: unknown[]) => api.getInvestmentFormConfig(...a),
  createInvestReturn: (...a: unknown[]) => api.createInvestReturn(...a),
}))

const access = vi.hoisted(() => ({
  value: { loading: false, hasAccess: (_key: string): boolean => true } as {
    loading: boolean
    hasAccess: (key: string) => boolean
  },
}))

vi.mock('../moduleAccess', () => ({
  useModuleAccess: () => access.value,
}))

const CONFIG = {
  allowed_return_types: ['проценты', 'тело_инвестиций'],
  return_type_choices: [
    { value: 'дивиденды', label: 'Дивиденды' },
    { value: 'проценты', label: 'Проценты' },
    { value: 'тело_инвестиций', label: 'Тело инвестиций' },
  ],
}

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="location">{`${location.pathname}${location.search}`}</div>
}

/** The router's navigate, to press the system «Назад». */
let routerNavigate: NavigateFunction | null = null
function NavigateProbe() {
  routerNavigate = useNavigate()
  return null
}

function renderPage(entries: string[] = ['/investments/returns/new']) {
  return render(
    <MemoryRouter initialEntries={entries} initialIndex={entries.length - 1}>
      <NavigateProbe />
      <Routes>
        <Route path="/home" element={<div>Главная</div>} />
        <Route path="/investments" element={<div>Инвестиции</div>} />
        <Route path="/investments/returns/new" element={<InvestReturnCreateMobilePage />} />
      </Routes>
      <LocationProbe />
    </MemoryRouter>,
  )
}

function deferred<T>() {
  let resolve!: (v: T) => void
  let reject!: (e: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

const currentPath = () => screen.getByTestId('location').textContent

async function sumInput() {
  return (await screen.findByLabelText('Сумма (USD)')) as HTMLInputElement
}

function typeSum(input: HTMLInputElement, value: string) {
  fireEvent.change(input, { target: { value } })
  fireEvent.blur(input)
}

const submitButton = () => screen.getByRole('button', { name: /Создать выплату/ })

function selectedText(id: string): string | null {
  const item = document.getElementById(id)?.closest('.ant-select')?.querySelector('.ant-select-selection-item')
  return item ? (item.textContent ?? '') : null
}

let successSpy: ReturnType<typeof vi.spyOn>
let errorSpy: ReturnType<typeof vi.spyOn>
let warningSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  access.value = { loading: false, hasAccess: () => true }
  vi.useFakeTimers({ toFake: ['Date'] })
  // 20 ноября 2026, 12:00 по Ташкенту: доступны октябрь, ноябрь и декабрь.
  vi.setSystemTime(new Date('2026-11-20T07:00:00Z'))
  api.getInvestmentFormConfig.mockReset().mockResolvedValue(CONFIG)
  api.createInvestReturn.mockReset().mockResolvedValue({})
  successSpy = vi.spyOn(message, 'success').mockImplementation(() => undefined as never)
  errorSpy = vi.spyOn(message, 'error').mockImplementation(() => undefined as never)
  warningSpy = vi.spyOn(message, 'warning').mockImplementation(() => undefined as never)
})

afterEach(() => {
  window.history.replaceState(null, '')
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('InvestReturnCreateMobilePage', () => {
  it('shows the seven fields with the desktop defaults in a full-screen form', async () => {
    const { container } = renderPage()
    const sum = await sumInput()

    expect(container.querySelector('.m-fullscreen')).not.toBeNull()
    expect(screen.getByRole('heading', { name: 'Новая выплата' })).toBeInTheDocument()
    for (const label of ['Месяц начисления', 'Дата', 'Валюта', 'Тип', 'Получатель', 'Комментарий']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
    expect(sum).toHaveValue('')
    expect(sum).toHaveAttribute('inputmode', 'decimal')
    expect(screen.getByLabelText('Дата')).toHaveValue('20.11.2026')
    expect(screen.getByLabelText('Месяц начисления')).toHaveValue('11.2026')
    expect(screen.getByLabelText('Месяц начисления')).toHaveAttribute('readonly')
    expect(screen.getByRole('radio', { name: 'USD' })).toBeChecked()
    expect(screen.getByRole('radio', { name: 'Инвестор' })).toBeChecked()
    // Только разрешённые типы, первый из них — по умолчанию.
    expect(selectedText('return-type')).toBe('Проценты')
    fireEvent.mouseDown(document.querySelector('#return-type')!.closest('.ant-select-selector')!)
    await waitFor(() => expect(document.querySelectorAll('.ant-select-item-option').length).toBe(2))
    expect([...document.querySelectorAll('.ant-select-item-option')].map((o) => o.textContent)).toEqual([
      'Проценты',
      'Тело инвестиций',
    ])
  })

  it('switches the sum label with the currency', async () => {
    renderPage()
    await sumInput()
    fireEvent.click(screen.getByText('UZS'))
    expect(await screen.findByLabelText('Сумма (UZS)')).toBeInTheDocument()
  })

  it('uses the default types when the form config does not load', async () => {
    api.getInvestmentFormConfig.mockRejectedValue(new Error('403'))
    renderPage()
    await sumInput()
    expect(selectedText('return-type')).toBe('Дивиденды')
  })

  it('shows the error under the sum and sends nothing without a sum', async () => {
    renderPage()
    const sum = await sumInput()

    fireEvent.click(submitButton())

    expect(await screen.findByText('Укажите сумму')).toBeInTheDocument()
    expect(sum).toHaveAttribute('aria-invalid', 'true')
    expect(sum).toHaveAccessibleDescription('Укажите сумму')
    expect(api.createInvestReturn).not.toHaveBeenCalled()

    typeSum(sum, '10')
    expect(screen.queryByText('Укажите сумму')).toBeNull()
  })

  it('refuses a month that stopped being allowed under the field, without a toast', async () => {
    renderPage()
    const sum = await sumInput()
    typeSum(sum, '1500')

    // Форму открыли 20-го, отправляют 21 декабря: ноябрь уже закрыт.
    vi.setSystemTime(new Date('2026-12-21T07:00:00Z'))
    fireEvent.click(submitButton())

    expect(await screen.findByText('Выберите допустимый месяц начисления')).toBeInTheDocument()
    expect(screen.getByLabelText('Месяц начисления')).toHaveAttribute('aria-invalid', 'true')
    expect(warningSpy).not.toHaveBeenCalled()
    expect(api.createInvestReturn).not.toHaveBeenCalled()
  })

  it('sends the desktop payload once, reports success and goes to /investments', async () => {
    renderPage()
    typeSum(await sumInput(), '1500')

    fireEvent.click(submitButton())

    await waitFor(() => expect(currentPath()).toBe('/investments'))
    expect(api.createInvestReturn).toHaveBeenCalledTimes(1)
    expect(api.createInvestReturn.mock.calls[0][0]).toEqual({
      date: '2026-11-20',
      billing_date: '2026-11-01',
      sum: '1500',
      currency: 'USD',
      type: 'проценты',
      recipient: 'инвестор',
      comment: '',
    })
    expect(successSpy).toHaveBeenCalledWith('Выплата создана и отправлена на согласование')
  })

  it('sends one request on a double tap', async () => {
    const pending = deferred<unknown>()
    api.createInvestReturn.mockReturnValue(pending.promise)
    renderPage()
    typeSum(await sumInput(), '1500')

    fireEvent.click(submitButton())
    fireEvent.click(submitButton())
    expect(submitButton()).toBeDisabled()

    await act(async () => {
      pending.resolve({})
    })
    await waitFor(() => expect(currentPath()).toBe('/investments'))
    expect(api.createInvestReturn).toHaveBeenCalledTimes(1)
  })

  it('keeps the typed values when the server refuses', async () => {
    api.createInvestReturn.mockRejectedValue(new Error('Сервер отклонил выплату'))
    renderPage()
    const sum = await sumInput()
    typeSum(sum, '1500')
    fireEvent.change(screen.getByLabelText('Комментарий'), { target: { value: 'За ноябрь' } })

    fireEvent.click(submitButton())

    await waitFor(() => expect(errorSpy).toHaveBeenCalledWith('Сервер отклонил выплату'))
    expect(currentPath()).toBe('/investments/returns/new')
    expect(screen.getByLabelText('Сумма (USD)')).toHaveValue('1500')
    expect(screen.getByLabelText('Комментарий')).toHaveValue('За ноябрь')
    expect(successSpy).not.toHaveBeenCalled()
    expect(submitButton()).not.toBeDisabled()
  })

  it('closes to /investments without a request', async () => {
    renderPage()
    await sumInput()
    fireEvent.click(screen.getByRole('button', { name: 'Закрыть' }))
    expect(currentPath()).toBe('/investments')
    expect(api.createInvestReturn).not.toHaveBeenCalled()
  })
})

describe('InvestReturnCreateMobilePage: leaving after the payout', () => {
  it('goes back to /investments it was opened from, without a second /investments in the history', async () => {
    renderPage(['/home', '/investments', '/investments/returns/new'])
    // BrowserRouter keeps the entry index in history.state; MemoryRouter does not, so it is set by hand.
    window.history.replaceState({ idx: 2 }, '')
    typeSum(await sumInput(), '1500')

    fireEvent.click(submitButton())

    await waitFor(() => expect(currentPath()).toBe('/investments'))
    act(() => {
      void routerNavigate?.(-1)
    })
    await waitFor(() => expect(currentPath()).toBe('/home'))
  })
})

describe('InvestReturnCreateMobilePage: access', () => {
  it('shows a skeleton while the modules load and requests nothing', () => {
    access.value = { loading: true, hasAccess: () => false }
    renderPage()

    expect(screen.getByTestId('mobile-state-loading')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Новая выплата' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Создать выплату/ })).toBeNull()
    expect(api.getInvestmentFormConfig).not.toHaveBeenCalled()
  })

  it('says the section is unavailable without the module and closes to /investments', async () => {
    access.value = { loading: false, hasAccess: () => false }
    renderPage()

    expect(screen.getByText('Раздел недоступен')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Создать выплату/ })).toBeNull()
    expect(screen.queryByLabelText('Сумма (USD)')).toBeNull()
    expect(api.getInvestmentFormConfig).not.toHaveBeenCalled()

    // «Закрыть» in the header and under the hint.
    const closeButtons = screen.getAllByRole('button', { name: 'Закрыть' })
    expect(closeButtons).toHaveLength(2)
    fireEvent.click(closeButtons[1])
    expect(currentPath()).toBe('/investments')
  })
})
