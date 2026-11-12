import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { message } from 'antd'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { InvestmentCreateMobilePage } from './InvestmentCreateMobilePage'

const api = vi.hoisted(() => ({
  getInvestmentFundingConfig: vi.fn(),
  createProjectInvestment: vi.fn(),
}))

vi.mock('../../lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/api')>()),
  getInvestmentFundingConfig: (...a: unknown[]) => api.getInvestmentFundingConfig(...a),
  createProjectInvestment: (...a: unknown[]) => api.createProjectInvestment(...a),
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

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="location">{`${location.pathname}${location.search}`}</div>
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/investments/new']}>
      <Routes>
        <Route path="/investments" element={<div>Инвестиции</div>} />
        <Route path="/investments/collect" element={<div>Мастер сбора</div>} />
        <Route path="/investments/new" element={<InvestmentCreateMobilePage />} />
      </Routes>
      <LocationProbe />
    </MemoryRouter>,
  )
}

function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

const currentPath = () => screen.getByTestId('location').textContent

async function sumInput(currency = 'USD') {
  return (await screen.findByLabelText(`Сумма (${currency})`)) as HTMLInputElement
}

function typeSum(input: HTMLInputElement, value: string) {
  fireEvent.change(input, { target: { value } })
  fireEvent.blur(input)
}

const submitButton = () => screen.getByRole('button', { name: /Отправить/ })

function selectedText(id: string): string | null {
  const item = document.getElementById(id)?.closest('.ant-select')?.querySelector('.ant-select-selection-item')
  return item ? (item.textContent ?? '') : null
}

async function chooseFundingMethod(label: string) {
  fireEvent.mouseDown(document.querySelector('#investment-funding-method')!.closest('.ant-select-selector')!)
  await waitFor(() => expect(document.querySelectorAll('.ant-select-item-option').length).toBe(2))
  const option = [...document.querySelectorAll('.ant-select-item-option')].find((o) => o.textContent === label)
  if (!option) throw new Error(`option ${label} not found`)
  fireEvent.click(option)
  await waitFor(() => expect(selectedText('investment-funding-method')).toBe(label))
}

let successSpy: ReturnType<typeof vi.spyOn>
let errorSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  access.value = { loading: false, hasAccess: () => true }
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date('2026-11-20T07:00:00Z'))
  api.getInvestmentFundingConfig.mockReset().mockResolvedValue({ is_enabled: false })
  api.createProjectInvestment.mockReset().mockResolvedValue({ id: 1 })
  successSpy = vi.spyOn(message, 'success').mockImplementation(() => undefined as never)
  errorSpy = vi.spyOn(message, 'error').mockImplementation(() => undefined as never)
})

afterEach(() => {
  cleanup()
  window.history.replaceState(null, '')
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('InvestmentCreateMobilePage', () => {
  it('shows the desktop fields with their defaults in a full-screen form', async () => {
    const { container } = renderPage()
    const sum = await sumInput()

    expect(container.querySelector('.m-fullscreen')).not.toBeNull()
    expect(screen.getByRole('heading', { name: 'Заявка на вложение' })).toBeInTheDocument()
    for (const label of ['Дата', 'Валюта', 'Способ внесения', 'Комментарий']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
    expect(screen.getByLabelText('Дата')).toHaveValue('20.11.2026')
    expect(sum).toHaveValue('')
    expect(sum).toHaveAttribute('inputmode', 'decimal')
    expect(screen.getByRole('radio', { name: 'USD' })).toBeChecked()
    expect(screen.getByRole('radio', { name: 'EUR' })).not.toBeChecked()
    expect(screen.getByRole('radio', { name: 'UZS' })).not.toBeChecked()
    // No funding method by default: the placeholder, not a value.
    expect(selectedText('investment-funding-method')).toBeNull()
    expect(screen.getByText('Выберите способ')).toBeInTheDocument()
    expect(screen.getByLabelText('Комментарий')).toHaveValue('')
  })

  it('clears the sum when the currency changes', async () => {
    renderPage()
    typeSum(await sumInput(), '1500')

    fireEvent.click(screen.getByText('UZS'))

    expect(await sumInput('UZS')).toHaveValue('')
    expect(screen.queryByLabelText('Сумма (USD)')).toBeNull()
  })

  it('shows the errors under the fields and sends nothing without a sum and a funding method', async () => {
    renderPage()
    const sum = await sumInput()

    fireEvent.click(submitButton())

    expect(await screen.findByText('Укажите сумму')).toBeInTheDocument()
    expect(screen.getByText('Укажите способ внесения')).toBeInTheDocument()
    expect(sum).toHaveAttribute('aria-invalid', 'true')
    expect(sum).toHaveAccessibleDescription('Укажите сумму')
    expect(api.createProjectInvestment).not.toHaveBeenCalled()

    typeSum(sum, '10')
    expect(screen.queryByText('Укажите сумму')).toBeNull()
    expect(screen.getByText('Укажите способ внесения')).toBeInTheDocument()

    await chooseFundingMethod('Наличными')
    expect(screen.queryByText('Укажите способ внесения')).toBeNull()
  })

  it('sends the desktop payload once, reports success and goes to /investments', async () => {
    renderPage()
    typeSum(await sumInput(), '1500')
    await chooseFundingMethod('Переводом на счёт')

    fireEvent.click(submitButton())

    await waitFor(() => expect(currentPath()).toBe('/investments'))
    expect(api.createProjectInvestment).toHaveBeenCalledTimes(1)
    expect(api.createProjectInvestment.mock.calls[0][0]).toEqual({
      date: '2026-11-20',
      amount: '1500',
      currency: 'USD',
      comment: '',
      funding_method: 'bank_transfer',
    })
    expect(successSpy).toHaveBeenCalledWith('Заявка на вложение создана')
    expect(errorSpy).not.toHaveBeenCalled()
  })

  it('sends the comment and another currency as typed', async () => {
    renderPage()
    await sumInput()
    fireEvent.click(screen.getByText('UZS'))
    typeSum(await sumInput('UZS'), '2000000')
    await chooseFundingMethod('Наличными')
    fireEvent.change(screen.getByLabelText('Комментарий'), { target: { value: 'Взнос партнёра' } })

    fireEvent.click(submitButton())

    await waitFor(() => expect(api.createProjectInvestment).toHaveBeenCalledTimes(1))
    expect(api.createProjectInvestment.mock.calls[0][0]).toEqual({
      date: '2026-11-20',
      amount: '2000000',
      currency: 'UZS',
      comment: 'Взнос партнёра',
      funding_method: 'cash',
    })
  })

  it('sends one request on a double tap', async () => {
    const pending = deferred<unknown>()
    api.createProjectInvestment.mockReturnValue(pending.promise)
    renderPage()
    typeSum(await sumInput(), '1500')
    await chooseFundingMethod('Наличными')

    fireEvent.click(submitButton())
    fireEvent.click(submitButton())
    expect(submitButton()).toBeDisabled()

    await act(async () => {
      pending.resolve({ id: 1 })
    })
    await waitFor(() => expect(currentPath()).toBe('/investments'))
    expect(api.createProjectInvestment).toHaveBeenCalledTimes(1)
  })

  it('keeps the typed values when the server refuses', async () => {
    api.createProjectInvestment.mockRejectedValue(new Error('Сервер отклонил заявку'))
    renderPage()
    typeSum(await sumInput(), '1500')
    await chooseFundingMethod('Наличными')
    fireEvent.change(screen.getByLabelText('Комментарий'), { target: { value: 'Взнос' } })

    fireEvent.click(submitButton())

    await waitFor(() => expect(errorSpy).toHaveBeenCalledWith('Сервер отклонил заявку'))
    expect(currentPath()).toBe('/investments/new')
    // InputNumber with precision 2 reformats the value on blur ("1500" → "1500.00").
    expect((screen.getByLabelText('Сумма (USD)') as HTMLInputElement).value).toMatch(/^1500(\.00)?$/)
    expect(selectedText('investment-funding-method')).toBe('Наличными')
    expect(screen.getByLabelText('Комментарий')).toHaveValue('Взнос')
    expect(successSpy).not.toHaveBeenCalled()
    expect(submitButton()).not.toBeDisabled()
  })

  it('closes to /investments without a request', async () => {
    renderPage()
    await sumInput()
    fireEvent.click(screen.getByRole('button', { name: 'Закрыть' }))
    expect(currentPath()).toBe('/investments')
    expect(api.createProjectInvestment).not.toHaveBeenCalled()
  })
})

describe('InvestmentCreateMobilePage: the investment mode', () => {
  it('shows a skeleton while the mode loads, without the form', () => {
    api.getInvestmentFundingConfig.mockReturnValue(new Promise(() => undefined))
    renderPage()

    expect(screen.getByTestId('mobile-state-loading')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Заявка на вложение' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Отправить/ })).toBeNull()
    expect(screen.queryByLabelText('Сумма (USD)')).toBeNull()
  })

  it('offers «Собрать из заявок» instead of the form in the investment mode', async () => {
    api.getInvestmentFundingConfig.mockResolvedValue({ is_enabled: true })
    renderPage()

    expect(await screen.findByText('Вложения собираются из заявок')).toBeInTheDocument()
    expect(screen.queryByLabelText('Сумма (USD)')).toBeNull()
    expect(screen.queryByRole('button', { name: /Отправить/ })).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: /Собрать из заявок/ }))
    expect(currentPath()).toBe('/investments/collect')
    expect(api.createProjectInvestment).not.toHaveBeenCalled()
  })

  it('shows the form when the mode config does not load, as the desktop does', async () => {
    api.getInvestmentFundingConfig.mockRejectedValue(new Error('403'))
    renderPage()
    expect(await sumInput()).toBeInTheDocument()
    expect(screen.queryByText('Вложения собираются из заявок')).toBeNull()
  })
})

describe('InvestmentCreateMobilePage: access', () => {
  it('says the section is unavailable without the module and requests nothing', () => {
    access.value = { loading: false, hasAccess: () => false }
    renderPage()

    expect(screen.getByText('Раздел недоступен')).toBeInTheDocument()
    expect(screen.queryByLabelText('Сумма (USD)')).toBeNull()
    expect(api.getInvestmentFundingConfig).not.toHaveBeenCalled()
  })
})
