import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { message } from 'antd'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { CashRegisterDto } from '../lib/api'
import { CashRegisterTransferTargetError } from '../lib/cashRegisterTransfer'
import { CashRegisterTransferMobilePage } from './CashRegisterTransferMobilePage'

const api = vi.hoisted(() => ({
  getCashRegisters: vi.fn(),
  getSettingsAccess: vi.fn(),
}))

vi.mock('../lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../lib/api')>()),
  getCashRegisters: (...a: unknown[]) => api.getCashRegisters(...a),
  getSettingsAccess: (...a: unknown[]) => api.getSettingsAccess(...a),
}))

const transfer = vi.hoisted(() => ({ submit: vi.fn() }))

// Only the sending is replaced: the error classes and texts are the real ones.
vi.mock('../lib/cashRegisterTransfer', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../lib/cashRegisterTransfer')>()),
  submitCashRegisterTransfer: (...a: unknown[]) => transfer.submit(...a),
}))

const access = vi.hoisted(() => ({
  value: { loading: false, hasAccess: (_key: string): boolean => true } as {
    loading: boolean
    hasAccess: (key: string) => boolean
  },
}))

vi.mock('./moduleAccess', () => ({
  useModuleAccess: () => access.value,
}))

const register = (id: number, name: string, currency: string, over: Partial<CashRegisterDto> = {}): CashRegisterDto => ({
  id,
  tenant: 1,
  currency,
  name,
  code: '',
  description: '',
  is_active: true,
  sort_order: id,
  is_default_for_currency: false,
  wallet_id: 100 + id,
  ...over,
})

const REGISTER_A = register(1, 'Касса А', 'UZS')
const REGISTER_B = register(2, 'Касса Б', 'UZS')
const REGISTER_INACTIVE = register(3, 'Касса закрытая', 'UZS', { is_active: false })
const REGISTER_USD = register(4, 'Касса долларовая', 'USD')

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="location">{location.pathname}</div>
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/cash/transfer']}>
      <Routes>
        <Route path="/cash" element={<div>Раздел Касса</div>} />
        <Route path="/cash/transfer" element={<CashRegisterTransferMobilePage />} />
      </Routes>
      <LocationProbe />
    </MemoryRouter>,
  )
}

const currentPath = () => screen.getByTestId('location').textContent

function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

/** Opens the select with this id and returns its dropdown (a new one: each select is opened once per test). */
async function openSelect(id: string): Promise<HTMLElement> {
  const before = new Set(document.querySelectorAll('.ant-select-dropdown'))
  fireEvent.mouseDown(document.getElementById(id)!.closest('.ant-select-selector')!)
  return waitFor(() => {
    const dropdown = [...document.querySelectorAll<HTMLElement>('.ant-select-dropdown')].find((d) => !before.has(d))
    if (!dropdown || dropdown.querySelectorAll('.ant-select-item-option').length === 0) throw new Error('no dropdown')
    return dropdown
  })
}

const optionTexts = (dropdown: HTMLElement) =>
  [...dropdown.querySelectorAll('.ant-select-item-option')].map((o) => o.textContent)

async function choose(id: string, label: string) {
  const dropdown = await openSelect(id)
  const option = [...dropdown.querySelectorAll('.ant-select-item-option')].find((o) => o.textContent === label)
  if (!option) throw new Error(`option ${label} not found`)
  fireEvent.click(option)
  await waitFor(() => expect(selectedText(id)).toBe(label))
}

function selectedText(id: string): string | null {
  const item = document.getElementById(id)?.closest('.ant-select')?.querySelector('.ant-select-selection-item')
  return item ? (item.textContent ?? '') : null
}

function typeNumber(input: HTMLElement, value: string) {
  fireEvent.change(input, { target: { value } })
  fireEvent.blur(input)
}

const submitButton = () => screen.getByRole('button', { name: /Отправить/ })

/** Waits for the registers, then fills «Из кассы» A, «В кассу» B and the sum. */
async function fillSameCurrency(amount = '50000') {
  await screen.findByLabelText('Из кассы')
  await choose('cash-transfer-from', 'Касса А')
  await choose('cash-transfer-to', 'Касса Б')
  typeNumber(screen.getByLabelText('Сумма (UZS)'), amount)
}

let successSpy: ReturnType<typeof vi.spyOn>
let warningSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  access.value = { loading: false, hasAccess: () => true }
  api.getCashRegisters.mockReset().mockResolvedValue([REGISTER_A, REGISTER_B, REGISTER_INACTIVE, REGISTER_USD])
  api.getSettingsAccess.mockReset().mockResolvedValue({ user_id: 555 })
  transfer.submit.mockReset().mockResolvedValue({ id: 900 })
  successSpy = vi.spyOn(message, 'success').mockImplementation(() => undefined as never)
  warningSpy = vi.spyOn(message, 'warning').mockImplementation(() => undefined as never)
})

afterEach(() => {
  cleanup()
  window.history.replaceState(null, '')
  vi.restoreAllMocks()
})

describe('CashRegisterTransferMobilePage', () => {
  it('loads the active registers into a full-screen form', async () => {
    const { container } = renderPage()
    expect(screen.getByTestId('mobile-state-loading')).toBeInTheDocument()
    await screen.findByLabelText('Из кассы')

    expect(container.querySelector('.m-fullscreen')).not.toBeNull()
    expect(screen.getByRole('heading', { name: 'Перевод между кассами' })).toBeInTheDocument()
    expect(screen.getByLabelText('В кассу')).toBeInTheDocument()
    expect(screen.getByLabelText('Сумма')).toBeInTheDocument()
    expect(screen.getByLabelText('Примечание')).toBeInTheDocument()
    expect(api.getCashRegisters).toHaveBeenCalledTimes(1)
    expect(api.getSettingsAccess).toHaveBeenCalledTimes(1)

    const dropdown = await openSelect('cash-transfer-from')
    expect(optionTexts(dropdown)).toEqual(['Касса А', 'Касса Б', 'Касса долларовая'])
  })

  it('does not offer the register chosen in the other field', async () => {
    renderPage()
    await screen.findByLabelText('Из кассы')
    await choose('cash-transfer-from', 'Касса А')

    const dropdown = await openSelect('cash-transfer-to')
    expect(optionTexts(dropdown)).toEqual(['Касса Б', 'Касса долларовая'])
  })

  it('shows the errors under the fields and sends nothing without the required fields', async () => {
    renderPage()
    await screen.findByLabelText('Из кассы')

    fireEvent.click(submitButton())

    expect(await screen.findByText('Выберите кассу-источник')).toBeInTheDocument()
    expect(screen.getByText('Выберите кассу-назначение')).toBeInTheDocument()
    expect(screen.getByText('Укажите сумму')).toBeInTheDocument()
    expect(screen.getByLabelText('Сумма')).toHaveAttribute('aria-invalid', 'true')
    expect(transfer.submit).not.toHaveBeenCalled()
    expect(currentPath()).toBe('/cash/transfer')
  })

  it('sends the transfer once, reports it and goes back to «Касса»', async () => {
    renderPage()
    await fillSameCurrency()
    fireEvent.change(screen.getByLabelText('Примечание'), { target: { value: 'На размен' } })
    // One currency: no credited sum is asked for.
    expect(screen.queryByLabelText(/Сумма зачисления/)).toBeNull()

    fireEvent.click(submitButton())

    await waitFor(() => expect(currentPath()).toBe('/cash'))
    expect(transfer.submit).toHaveBeenCalledTimes(1)
    expect(transfer.submit).toHaveBeenCalledWith({
      fromRegister: REGISTER_A,
      toRegister: REGISTER_B,
      amount: 50000,
      note: 'На размен',
      toAmount: undefined,
      requesterId: 555,
    })
    expect(successSpy).toHaveBeenCalledWith('Заявка на перевод создана и отправлена на согласование')
    expect(screen.getByText('Раздел Касса')).toBeInTheDocument()
  })

  it('asks for the credited sum when the registers have different currencies', async () => {
    renderPage()
    await screen.findByLabelText('Из кассы')
    await choose('cash-transfer-from', 'Касса А')
    await choose('cash-transfer-to', 'Касса долларовая')
    typeNumber(screen.getByLabelText('Сумма (UZS)'), '1270000')

    expect(screen.getByTestId('cash-transfer-currency-warning')).toHaveTextContent('Кассы в разных валютах')
    const toAmount = screen.getByLabelText('Сумма зачисления (USD)')

    fireEvent.click(submitButton())
    expect(await screen.findByText('Укажите сумму зачисления')).toBeInTheDocument()
    expect(transfer.submit).not.toHaveBeenCalled()

    typeNumber(toAmount, '100')
    fireEvent.click(submitButton())

    await waitFor(() => expect(transfer.submit).toHaveBeenCalledTimes(1))
    expect(transfer.submit).toHaveBeenCalledWith(
      expect.objectContaining({ fromRegister: REGISTER_A, toRegister: REGISTER_USD, amount: 1270000, toAmount: 100 }),
    )
    await waitFor(() => expect(currentPath()).toBe('/cash'))
  })

  it('warns and leaves the form when the request went to approval without the target register', async () => {
    transfer.submit.mockRejectedValue(new CashRegisterTransferTargetError(901, new Error('Нет связи')))
    renderPage()
    await fillSameCurrency()

    fireEvent.click(submitButton())

    await waitFor(() => expect(currentPath()).toBe('/cash'))
    expect(warningSpy).toHaveBeenCalledTimes(1)
    expect(warningSpy).toHaveBeenCalledWith(expect.stringContaining('Заявка №901 отправлена на согласование'), 10)
    expect(successSpy).not.toHaveBeenCalled()
    expect(transfer.submit).toHaveBeenCalledTimes(1)
  })

  it('shows any other error on the form and keeps the values', async () => {
    transfer.submit.mockRejectedValue(new Error('Сервер недоступен'))
    renderPage()
    await fillSameCurrency()

    fireEvent.click(submitButton())

    expect(await screen.findByText('Сервер недоступен')).toBeInTheDocument()
    expect(currentPath()).toBe('/cash/transfer')
    expect(selectedText('cash-transfer-from')).toBe('Касса А')
    expect(selectedText('cash-transfer-to')).toBe('Касса Б')
    expect(screen.getByLabelText('Сумма (UZS)')).toHaveValue('50000')
    expect(successSpy).not.toHaveBeenCalled()
    await waitFor(() => expect(submitButton()).not.toBeDisabled())
  })

  it('sends one request on a double tap', async () => {
    const pending = deferred<{ id: number }>()
    transfer.submit.mockReturnValue(pending.promise)
    renderPage()
    await fillSameCurrency()

    fireEvent.click(submitButton())
    fireEvent.click(submitButton())

    expect(transfer.submit).toHaveBeenCalledTimes(1)
    pending.resolve({ id: 900 })
    await waitFor(() => expect(currentPath()).toBe('/cash'))
    expect(transfer.submit).toHaveBeenCalledTimes(1)
    expect(successSpy).toHaveBeenCalledTimes(1)
  })

  it('shows an error state when the registers do not load', async () => {
    api.getCashRegisters.mockRejectedValue(new Error('Нет доступа к кассам'))
    renderPage()
    expect(await screen.findByText('Нет доступа к кассам')).toBeInTheDocument()
    expect(screen.getByText('Не удалось загрузить кассы')).toBeInTheDocument()
    expect(screen.queryByLabelText('Из кассы')).toBeNull()

    api.getCashRegisters.mockResolvedValue([REGISTER_A, REGISTER_B])
    fireEvent.click(screen.getByRole('button', { name: /Повторить/ }))
    expect(await screen.findByLabelText('Из кассы')).toBeInTheDocument()
  })

  it('shows «Раздел недоступен» without the cash module and requests nothing', () => {
    access.value = { loading: false, hasAccess: (key) => key !== 'cash' }
    renderPage()
    expect(screen.getByText('Раздел недоступен')).toBeInTheDocument()
    expect(api.getCashRegisters).not.toHaveBeenCalled()
    expect(api.getSettingsAccess).not.toHaveBeenCalled()

    // «Закрыть» in the header and in the empty state lead to the same place.
    fireEvent.click(screen.getAllByRole('button', { name: 'Закрыть' })[1])
    expect(currentPath()).toBe('/cash')
  })
})
