import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MobileShellContext, type MobileShellContextValue } from '../mobileShell'
import { RequestsMobilePage } from './RequestsMobilePage'

const api = vi.hoisted(() => ({
  fetchCursorListPage: vi.fn(),
  getRequestCategories: vi.fn(),
  getRequestFormOptions: vi.fn(),
  getRequestVendors: vi.fn(),
  getInvestmentFundingConfig: vi.fn(),
}))

vi.mock('../../lib/api', () => ({
  fetchCursorListPage: (...args: unknown[]) => api.fetchCursorListPage(...args),
  getRequestCategories: (...args: unknown[]) => api.getRequestCategories(...args),
  getRequestFormOptions: (...args: unknown[]) => api.getRequestFormOptions(...args),
  getRequestVendors: (...args: unknown[]) => api.getRequestVendors(...args),
  getInvestmentFundingConfig: (...args: unknown[]) => api.getInvestmentFundingConfig(...args),
}))

vi.mock('../../lib/useActionItems', () => ({
  useActionItems: () => ({ items: [], count: 0, loading: false, error: false, refresh: vi.fn() }),
  refreshActionItems: vi.fn(),
}))

vi.mock('../company', () => ({
  useCompany: () => ({ enabled: false, current: null, companies: [], currentCompany: null, switchCompany: () => undefined }),
}))

const SHELL: MobileShellContextValue = {
  userId: 42,
  userIdStatus: 'ready',
  openCompanySwitcher: () => undefined,
  headerStore: null,
}

function renderFeed() {
  return render(
    <MobileShellContext.Provider value={SHELL}>
      <MemoryRouter initialEntries={['/requests?tab=all']}>
        <RequestsMobilePage />
      </MemoryRouter>
    </MobileShellContext.Provider>,
  )
}

/** Query of the last list request, without the page size the feed adds. */
function lastQuery(): Record<string, string> {
  const calls = api.fetchCursorListPage.mock.calls
  const url = String(calls[calls.length - 1][0])
  const params = Object.fromEntries(new URLSearchParams(url.split('?')[1] ?? ''))
  delete params.page_size
  return params
}

function chipLabels(): string[] {
  const list = screen.queryByRole('list', { name: 'Выбранные фильтры' })
  if (!list) return []
  return within(list)
    .getAllByRole('button')
    .map((button) => button.getAttribute('aria-label') ?? '')
}

async function openSheet() {
  fireEvent.click(screen.getByRole('button', { name: /^Фильтры/ }))
  return screen.findByRole('dialog', { name: 'Фильтры' })
}

beforeEach(() => {
  sessionStorage.clear()
  api.fetchCursorListPage.mockImplementation(async () => ({
    results: [{ id: 1, title: 'Аренда', amount: 10, currency: 'UZS', status: 'APPROVED' }],
    next: null,
    previous: null,
  }))
  api.getRequestCategories.mockResolvedValue([{ id: 1, name: 'Офис' }])
  api.getRequestFormOptions.mockResolvedValue({ requester_candidates: [{ id: 7, username: 'ivanov' }] })
  api.getRequestVendors.mockResolvedValue(['ООО Альфа', 'Бета Строй'])
  api.getInvestmentFundingConfig.mockResolvedValue({ is_enabled: false })
  vi.stubGlobal(
    'IntersectionObserver',
    class {
      disconnect() {}
      observe() {}
      unobserve() {}
    },
  )
  window.scrollTo = vi.fn() as unknown as typeof window.scrollTo
})

afterEach(() => {
  // Unmount before dropping the stubs: a late feed effect must not meet a missing IntersectionObserver.
  cleanup()
  vi.unstubAllGlobals()
})

async function applyThreeFilters() {
  renderFeed()
  await screen.findByText('Аренда')
  const sheet = await openSheet()
  fireEvent.click(within(within(sheet).getByRole('group', { name: 'Статус' })).getByRole('button', { name: 'Оплачена' }))
  fireEvent.click(within(within(sheet).getByRole('group', { name: 'Валюта' })).getByRole('button', { name: 'USD' }))
  fireEvent.click(within(sheet).getByRole('switch', { name: 'Только с амортизацией' }))
  fireEvent.click(within(sheet).getByRole('button', { name: 'Показать' }))
  await waitFor(() => expect(lastQuery()).toEqual({ status: 'PAYED', currency: 'USD', amortized_only: '1' }))
}

describe('RequestsFilterSheet', () => {
  it('applies three filters: the list query, three chips and a count of 3', async () => {
    await applyThreeFilters()
    expect(chipLabels()).toEqual([
      'Убрать фильтр: Оплачена',
      'Убрать фильтр: USD',
      'Убрать фильтр: С амортизацией',
    ])
    expect(screen.getByRole('button', { name: 'Фильтры, выбрано: 3' })).toBeInTheDocument()
  })

  it('clears one filter from the cross of its chip', async () => {
    await applyThreeFilters()
    fireEvent.click(screen.getByRole('button', { name: 'Убрать фильтр: USD' }))
    await waitFor(() => expect(lastQuery()).toEqual({ status: 'PAYED', amortized_only: '1' }))
    expect(chipLabels()).toHaveLength(2)
    expect(screen.getByRole('button', { name: 'Фильтры, выбрано: 2' })).toBeInTheDocument()
  })

  it('clears everything with «Сбросить»', async () => {
    await applyThreeFilters()
    const sheet = await openSheet()
    expect(within(within(sheet).getByRole('group', { name: 'Валюта' })).getByRole('button', { name: 'USD' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    fireEvent.click(within(sheet).getByRole('button', { name: 'Сбросить' }))
    expect(within(within(sheet).getByRole('group', { name: 'Валюта' })).getByRole('button', { name: 'USD' })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
    expect(within(sheet).getByRole('switch', { name: 'Только с амортизацией' })).not.toBeChecked()
    fireEvent.click(within(sheet).getByRole('button', { name: 'Показать' }))
    await waitFor(() => expect(lastQuery()).toEqual({}))
    expect(chipLabels()).toEqual([])
    expect(screen.getByRole('button', { name: 'Фильтры' })).toBeInTheDocument()
  })

  it('keeps the other fields of the sheet while the vendor is picked on its own screen', async () => {
    renderFeed()
    await screen.findByText('Аренда')
    const sheet = await openSheet()
    fireEvent.click(within(within(sheet).getByRole('group', { name: 'Валюта' })).getByRole('button', { name: 'USD' }))
    fireEvent.change(within(sheet).getByRole('spinbutton', { name: 'Сумма от' }), { target: { value: '1000' } })

    fireEvent.click(within(sheet).getByRole('button', { name: 'Поставщик: любой' }))
    const picker = await screen.findByRole('list', { name: 'Поставщик' })
    fireEvent.click(within(picker).getByRole('button', { name: 'ООО Альфа' }))
    await waitFor(() => expect(screen.queryByRole('list', { name: 'Поставщик' })).toBeNull())

    expect(within(sheet).getByRole('button', { name: 'Поставщик: ООО Альфа' })).toBeInTheDocument()
    expect(within(within(sheet).getByRole('group', { name: 'Валюта' })).getByRole('button', { name: 'USD' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(within(sheet).getByRole('spinbutton', { name: 'Сумма от' })).toHaveValue('1000')

    fireEvent.click(within(sheet).getByRole('button', { name: 'Показать' }))
    await waitFor(() => expect(lastQuery()).toEqual({ currency: 'USD', vendor: 'ООО Альфа', amount_min: '1000' }))
    expect(api.getRequestVendors).toHaveBeenCalledTimes(1)
  })

  it('does not touch the feed until «Показать»', async () => {
    renderFeed()
    await screen.findByText('Аренда')
    const callsBefore = api.fetchCursorListPage.mock.calls.length
    const sheet = await openSheet()
    fireEvent.click(within(within(sheet).getByRole('group', { name: 'Валюта' })).getByRole('button', { name: 'EUR' }))
    fireEvent.click(within(sheet).getByRole('button', { name: 'Закрыть' }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Фильтры' })).toBeNull())
    expect(api.fetchCursorListPage.mock.calls.length).toBe(callsBefore)
    expect(chipLabels()).toEqual([])
  })
})
