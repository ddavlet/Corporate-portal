import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { message } from 'antd'
import { MemoryRouter, Route, Routes, useLocation, useNavigate, type NavigateFunction } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { InvestmentCollectMobilePage } from './InvestmentCollectMobilePage'

const api = vi.hoisted(() => ({
  getFundingPool: vi.fn(),
  createInvestmentsFromRequests: vi.fn(),
}))

vi.mock('../../lib/api', () => ({
  getFundingPool: (...a: unknown[]) => api.getFundingPool(...a),
  createInvestmentsFromRequests: (...a: unknown[]) => api.createInvestmentsFromRequests(...a),
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

function req(id: number, over: Record<string, unknown> = {}) {
  return {
    id,
    submitted_at: '2026-10-01T10:00:00Z',
    kind: 'expense',
    payment_type: 'Наличные',
    payment_purpose: 'Закупка',
    description: 'компьютер',
    amount: '5000000',
    currency: 'UZS',
    status: 'approved',
    is_payed: false,
    ...over,
  }
}

function pool(over: Record<string, unknown> = {}) {
  return {
    cash: {
      requests: [
        req(10, { is_payed: true }),
        req(11, { kind: 'transfer', payment_purpose: 'Перевод между кассами', description: '', amount: '1000000' }),
      ],
      totals: [],
    },
    bank_transfer: { requests: [req(20, { payment_type: 'Перечисление', amount: '3000000' })], totals: [] },
    approval_chain_ok: true,
    ...over,
  }
}

function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="location">{location.pathname}</div>
}

/** The router's navigate, to press the system «Назад» as a phone gesture or the browser does. */
let routerNavigate: NavigateFunction | null = null
function NavigateProbe() {
  routerNavigate = useNavigate()
  return null
}
function historyBack() {
  act(() => {
    void routerNavigate?.(-1)
  })
}

type Entry = string | { pathname: string; state?: unknown }

function renderPage(entries: Entry[] = ['/investments', '/investments/collect']) {
  return render(
    <MemoryRouter initialEntries={entries} initialIndex={entries.length - 1}>
      <NavigateProbe />
      <Routes>
        <Route path="/home" element={<div>Главная</div>} />
        <Route path="/investments" element={<div>Инвестиции</div>} />
        <Route path="/investments/collect" element={<InvestmentCollectMobilePage />} />
      </Routes>
      <LocationProbe />
    </MemoryRouter>,
  )
}

const currentPath = () => screen.getByTestId('location').textContent
/** The current step of the progress bar as «Шаг N из M · Title» (the step is marked with aria-current). */
function stepText(): string {
  const items = within(screen.getByRole('navigation', { name: 'Шаги' })).getAllByRole('listitem')
  const index = items.findIndex((li) => li.getAttribute('aria-current') === 'step')
  return `Шаг ${index + 1} из ${items.length} · ${items[index]?.textContent ?? ''}`
}
const totalsText = () => screen.getByTestId('collect-totals').textContent
const checkbox = (id: number) => screen.getByRole('checkbox', { name: new RegExp(`Заявка №${id},`) })

async function chooseMethod(name: RegExp = /^Наличными/) {
  fireEvent.click(await screen.findByRole('button', { name }))
  await screen.findByRole('button', { name: 'Назад' })
}

async function toReview(method?: RegExp) {
  await chooseMethod(method)
  fireEvent.click(screen.getByRole('button', { name: 'Далее' }))
  return (await screen.findByLabelText('Описание')) as HTMLTextAreaElement
}

const createButton = () => screen.queryByRole('button', { name: /Создать вложение/ })

let successSpy: ReturnType<typeof vi.spyOn>
let errorSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  access.value = { loading: false, hasAccess: () => true }
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date('2026-11-12T07:00:00Z'))
  api.getFundingPool.mockReset().mockResolvedValue(pool())
  api.createInvestmentsFromRequests
    .mockReset()
    .mockResolvedValue({ investments: [{ id: 77, date: '2026-11-12', rate_date: '2026-11-12' }] })
  successSpy = vi.spyOn(message, 'success').mockImplementation(() => undefined as never)
  errorSpy = vi.spyOn(message, 'error').mockImplementation(() => undefined as never)
})

afterEach(() => {
  window.history.replaceState(null, '')
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('InvestmentCollectMobilePage: loading and the method', () => {
  it('offers both methods with their counts in a full-screen wizard', async () => {
    const { container } = renderPage()

    expect(await screen.findByRole('button', { name: 'Наличными (2)' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Переводом на счёт (1)' })).toBeInTheDocument()
    expect(container.querySelector('.m-fullscreen')).not.toBeNull()
    expect(screen.getByRole('heading', { name: 'Собрать из заявок' })).toBeInTheDocument()
    expect(stepText()).toBe('Шаг 1 из 3 · Способ внесения')
    expect(screen.getByRole('button', { name: 'Закрыть' })).toBeInTheDocument()
  })

  it('shows the load error with a retry', async () => {
    api.getFundingPool.mockRejectedValueOnce(new Error('Сервер недоступен'))
    renderPage()

    expect(await screen.findByText('Сервер недоступен')).toBeInTheDocument()
    expect(screen.getByTestId('mobile-state-error')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Повторить/ }))

    expect(await screen.findByRole('button', { name: 'Наличными (2)' })).toBeInTheDocument()
    expect(api.getFundingPool).toHaveBeenCalledTimes(2)
  })

  it('shows the server text without the investment mode and no method buttons', async () => {
    api.getFundingPool.mockRejectedValue(new Error('Инвестиционный режим не включён'))
    renderPage()

    expect(await screen.findByText('Инвестиционный режим не включён')).toBeInTheDocument()
    expect(screen.getByTestId('mobile-state-error')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Наличными/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /^Переводом на счёт/ })).toBeNull()
  })
})

describe('InvestmentCollectMobilePage: the requests', () => {
  it('shows every request as a selected card, grouped for cash, and updates the totals', async () => {
    renderPage()
    await chooseMethod()

    expect(stepText()).toBe('Шаг 2 из 3 · Заявки')
    expect(screen.getByRole('heading', { name: 'Расходы' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Перемещения' })).toBeInTheDocument()
    expect(checkbox(10)).toBeChecked()
    expect(checkbox(11)).toBeChecked()
    expect(screen.getByText('№10')).toBeInTheDocument()
    expect(screen.getByText('Перевод между кассами')).toBeInTheDocument()
    expect(screen.getByText('компьютер')).toBeInTheDocument()
    // The tone tag of the mobile screens (dark text on the light fill), not antd's preset below 4.5:1.
    expect(screen.getByText('Выплачена').closest('[data-tone]')).toHaveAttribute('data-tone', 'success')
    expect(totalsText()).toMatch(/^Итого: 6\s?000\s?000 UZS \(2 заявки\)$/)

    fireEvent.click(checkbox(11))
    expect(checkbox(11)).not.toBeChecked()
    expect(totalsText()).toMatch(/^Итого: 5\s?000\s?000 UZS \(1 заявка\)$/)
  })

  it('says nothing is selected and blocks «Далее»', async () => {
    renderPage()
    await chooseMethod()

    fireEvent.click(checkbox(10))
    fireEvent.click(checkbox(11))

    expect(totalsText()).toBe('Итого: ничего не выбрано')
    expect(screen.getByRole('button', { name: 'Далее' })).toBeDisabled()
  })

  it('says there is nothing to collect for an empty method and leads back to the method', async () => {
    api.getFundingPool.mockResolvedValue(pool({ bank_transfer: { requests: [], totals: [] } }))
    renderPage()
    await chooseMethod(/^Переводом на счёт/)

    expect(screen.getByText('Нет заявок для сбора')).toBeInTheDocument()
    expect(screen.getByText(/«Переводом на счёт» — заявок, которые можно собрать во вложение, нет/)).toBeInTheDocument()
    // No footer with an empty total and a dead «Далее».
    expect(screen.queryByRole('button', { name: 'Далее' })).toBeNull()
    expect(screen.queryByTestId('collect-totals')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Выбрать другой способ' }))
    await waitFor(() => expect(stepText()).toBe('Шаг 1 из 3 · Способ внесения'))
    expect(screen.getByRole('button', { name: 'Наличными (2)' })).toBeInTheDocument()
  })
})

describe('InvestmentCollectMobilePage: review and create', () => {
  it('warns about the missing approval chain', async () => {
    api.getFundingPool.mockResolvedValue(pool({ approval_chain_ok: false }))
    renderPage()
    await toReview()
    expect(screen.getByText('Вложения не будут подтверждаться — не настроено согласование')).toBeInTheDocument()
  })

  it('previews the description and sends an empty comment without an edit', async () => {
    renderPage()
    const description = await toReview()

    expect(stepText()).toBe('Шаг 3 из 3 · Проверка')
    expect(description).toHaveValue('На основании заявок №10, №11. №10 — компьютер; №11 — перевод между кассами')
    expect(screen.queryByText('Вложения не будут подтверждаться — не настроено согласование')).toBeNull()

    fireEvent.click(createButton()!)

    await waitFor(() => expect(api.createInvestmentsFromRequests).toHaveBeenCalledTimes(1))
    expect(api.createInvestmentsFromRequests).toHaveBeenCalledWith({ funding_method: 'cash', request_ids: [10, 11], comment: '' })
  })

  it('sends the edited description', async () => {
    renderPage()
    const description = await toReview(/^Переводом на счёт/)
    fireEvent.change(description, { target: { value: 'Своё описание' } })

    fireEvent.click(createButton()!)

    await waitFor(() => expect(api.createInvestmentsFromRequests).toHaveBeenCalledTimes(1))
    expect(api.createInvestmentsFromRequests).toHaveBeenCalledWith({
      funding_method: 'bank_transfer',
      request_ids: [20],
      comment: 'Своё описание',
    })
  })

  it('sends one request on a double tap', async () => {
    const pending = deferred<{ investments: { id: number; date: string }[] }>()
    api.createInvestmentsFromRequests.mockReturnValue(pending.promise)
    renderPage()
    await toReview()

    fireEvent.click(createButton()!)
    fireEvent.click(createButton()!)
    expect(createButton()).toBeDisabled()

    await act(async () => {
      pending.resolve({ investments: [{ id: 78, date: '2026-11-12' }] })
    })
    expect(await screen.findByText('Создано вложений: №78')).toBeInTheDocument()
    expect(api.createInvestmentsFromRequests).toHaveBeenCalledTimes(1)
  })

  it('shows the result without the CBU warning and leads back to /investments', async () => {
    renderPage()
    await toReview()
    fireEvent.click(createButton()!)

    expect(await screen.findByText('Создано вложений: №77')).toBeInTheDocument()
    expect(successSpy).toHaveBeenCalledWith('Создано вложений: №77')
    expect(screen.queryByText(/Курс ЦБ может быть неактуален/)).toBeNull()
    expect(createButton()).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'К инвестициям' }))
    expect(currentPath()).toBe('/investments')
  })

  it('warns about a stale CBU rate of the created investments', async () => {
    api.createInvestmentsFromRequests.mockResolvedValue({
      investments: [
        { id: 77, date: '2026-11-12', rate_date: '2026-11-05' },
        { id: 78, date: '2026-11-12', rate_date: '2026-11-12' },
      ],
    })
    renderPage()
    await toReview()
    fireEvent.click(createButton()!)

    expect(await screen.findByText('Создано вложений: №77, №78')).toBeInTheDocument()
    expect(screen.getByText(/Курс ЦБ может быть неактуален/)).toBeInTheDocument()
  })

  it('keeps the selection and the description when the server refuses', async () => {
    api.createInvestmentsFromRequests.mockRejectedValue(new Error('Заявка №11 уже собрана'))
    renderPage()
    await chooseMethod()
    fireEvent.click(checkbox(11))
    fireEvent.click(screen.getByRole('button', { name: 'Далее' }))
    const description = (await screen.findByLabelText('Описание')) as HTMLTextAreaElement
    fireEvent.change(description, { target: { value: 'Своё описание' } })

    fireEvent.click(createButton()!)

    await waitFor(() => expect(errorSpy).toHaveBeenCalledWith('Заявка №11 уже собрана'))
    expect(api.createInvestmentsFromRequests.mock.calls[0][0]).toMatchObject({ request_ids: [10] })
    expect(screen.getByLabelText('Описание')).toHaveValue('Своё описание')
    expect(totalsText()).toMatch(/\(1 заявка\)$/)
    expect(createButton()).not.toBeDisabled()
    expect(stepText()).toBe('Шаг 3 из 3 · Проверка')
  })
})

describe('InvestmentCollectMobilePage: «Назад»', () => {
  it('goes one step back with the header button and closes from the first step', async () => {
    renderPage()
    await toReview()

    fireEvent.click(screen.getByRole('button', { name: 'Назад' }))
    await waitFor(() => expect(stepText()).toBe('Шаг 2 из 3 · Заявки'))
    fireEvent.click(screen.getByRole('button', { name: 'Назад' }))
    await waitFor(() => expect(stepText()).toBe('Шаг 1 из 3 · Способ внесения'))

    fireEvent.click(screen.getByRole('button', { name: 'Закрыть' }))
    expect(currentPath()).toBe('/investments')
    expect(api.getFundingPool).toHaveBeenCalledTimes(1)
    expect(api.createInvestmentsFromRequests).not.toHaveBeenCalled()
  })

  it('goes one step back with the system «Назад»', async () => {
    renderPage()
    await toReview()

    historyBack()
    await waitFor(() => expect(stepText()).toBe('Шаг 2 из 3 · Заявки'))
    expect(checkbox(10)).toBeChecked()
    historyBack()
    await waitFor(() => expect(stepText()).toBe('Шаг 1 из 3 · Способ внесения'))
    expect(api.createInvestmentsFromRequests).not.toHaveBeenCalled()
  })

  it('leaves to /investments with the system «Назад» from the result and creates nothing twice', async () => {
    renderPage()
    await toReview()
    fireEvent.click(createButton()!)
    expect(await screen.findByText('Создано вложений: №77')).toBeInTheDocument()

    historyBack()

    await waitFor(() => expect(currentPath()).toBe('/investments'))
    expect(createButton()).toBeNull()
    expect(api.createInvestmentsFromRequests).toHaveBeenCalledTimes(1)
  })
})

describe('InvestmentCollectMobilePage: a reload in the middle', () => {
  it.each([1, 2])('starts again from the method when the page loads on step %i', async (collectStep) => {
    renderPage(['/investments', { pathname: '/investments/collect', state: { collectStep } }])

    expect(await screen.findByRole('button', { name: 'Наличными (2)' })).toBeInTheDocument()
    expect(stepText()).toBe('Шаг 1 из 3 · Способ внесения')
    expect(screen.queryByLabelText('Описание')).toBeNull()
    expect(screen.queryByRole('button', { name: /Создать вложение/ })).toBeNull()
    expect(screen.getByRole('button', { name: 'Закрыть' })).toBeInTheDocument()
  })

  it('collects with the method picked after the reload', async () => {
    renderPage(['/investments', { pathname: '/investments/collect', state: { collectStep: 2 } }])

    const description = await toReview(/^Переводом на счёт/)
    expect(stepText()).toBe('Шаг 3 из 3 · Проверка')
    expect(screen.getByText('Переводом на счёт, выбрано заявок: 1')).toBeInTheDocument()
    expect(description).toHaveValue('На основании заявки №20. №20 — компьютер')

    fireEvent.click(createButton()!)
    await waitFor(() => expect(api.createInvestmentsFromRequests).toHaveBeenCalledTimes(1))
    expect(api.createInvestmentsFromRequests.mock.calls[0][0]).toMatchObject({
      funding_method: 'bank_transfer',
      request_ids: [20],
    })
  })
})

describe('InvestmentCollectMobilePage: leaving the result', () => {
  it('goes back past the steps to /investments, without a second /investments in the history', async () => {
    renderPage(['/home', '/investments', '/investments/collect'])
    await toReview()
    fireEvent.click(createButton()!)
    expect(await screen.findByText('Создано вложений: №77')).toBeInTheDocument()

    // BrowserRouter keeps the entry index in history.state; MemoryRouter does not, so it is set by hand:
    // /home 0, /investments 1, the method 2, the requests 3, the result 4.
    window.history.replaceState({ idx: 4 }, '')
    fireEvent.click(screen.getByRole('button', { name: 'К инвестициям' }))
    await waitFor(() => expect(currentPath()).toBe('/investments'))

    historyBack()
    await waitFor(() => expect(currentPath()).toBe('/home'))
    expect(api.createInvestmentsFromRequests).toHaveBeenCalledTimes(1)
  })
})

describe('InvestmentCollectMobilePage: access', () => {
  it('shows a skeleton while the modules load and requests nothing', () => {
    access.value = { loading: true, hasAccess: () => false }
    renderPage()

    expect(screen.getByTestId('mobile-state-loading')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Собрать из заявок' })).toBeInTheDocument()
    expect(api.getFundingPool).not.toHaveBeenCalled()
  })

  it('says the section is unavailable without the module and closes to /investments', () => {
    access.value = { loading: false, hasAccess: () => false }
    renderPage(['/investments/collect'])

    expect(screen.getByText('Раздел недоступен')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Наличными/ })).toBeNull()
    expect(api.getFundingPool).not.toHaveBeenCalled()

    const closeButtons = screen.getAllByRole('button', { name: 'Закрыть' })
    expect(closeButtons).toHaveLength(2)
    fireEvent.click(closeButtons[1])
    expect(currentPath()).toBe('/investments')
  })
})
