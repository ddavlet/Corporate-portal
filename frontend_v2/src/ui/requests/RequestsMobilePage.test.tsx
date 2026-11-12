import { useSyncExternalStore } from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ActionItem } from '../../lib/actionItemsApi'
import { MobileShellContext, createMobileHeaderStore, type MobileHeaderStore, type MobileShellContextValue } from '../mobileShell'
import { resetViewport, setViewport } from '../../test/viewport'
import { REQUESTS_MOBILE_SESSION_KEY, RequestsMobilePage } from './RequestsMobilePage'
import { RequestsRoute } from './RequestsRoute'

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

const actionItems = vi.hoisted(() => ({
  state: { items: [] as ActionItem[], count: 0, loading: false, error: false },
  refresh: vi.fn(),
}))

vi.mock('../../lib/useActionItems', () => ({
  useActionItems: () => ({ ...actionItems.state, refresh: actionItems.refresh }),
  refreshActionItems: () => actionItems.refresh(),
}))

const company = vi.hoisted(() => ({ value: { enabled: false, current: null as string | null } }))

vi.mock('../company', () => ({
  useCompany: () => ({ ...company.value, companies: [], currentCompany: null, switchCompany: () => undefined }),
}))

vi.mock('./RequestsPage', () => ({ RequestsPage: () => <div>Десктопный список заявок</div> }))

function actionItem(id: number, kind: ActionItem['kind'], subdomain?: string): ActionItem {
  return {
    kind,
    id,
    approval_id: id * 10,
    step: 2,
    step_type: 'approval',
    title: `Заявка ${id}`,
    amount: '1500000.00',
    currency: 'UZS',
    type_code: 'transfer',
    type_label: 'Перечисление',
    created_at: '2026-11-10T09:00:00Z',
    link: `/requests/${id}`,
    ...(subdomain ? { tenant: { subdomain, name: subdomain.toUpperCase() } } : {}),
  }
}

function row(id: number, overrides: Record<string, unknown> = {}) {
  return {
    id,
    title: `Аренда офиса ${id}`,
    amount: 2500000,
    currency: 'UZS',
    status: 'APPROVED',
    payment_type: 'Перечисление',
    vendor: 'ООО Альфа',
    requester: 3,
    requester_username: 'ivanov',
    submitted_at: '2026-11-05T10:00:00Z',
    expense_link: { module: 'bank', id: 5 },
    ...overrides,
  }
}

function page(results: unknown[], next: string | null = null) {
  return { results, next, previous: null }
}

/** The URLs the feed asked for, in order. */
function requestedUrls(): string[] {
  return api.fetchCursorListPage.mock.calls.map((call) => String(call[0]))
}

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="location">{`${location.pathname}${location.search}`}</div>
}

function HeaderProbe({ store }: { store: MobileHeaderStore }) {
  const config = useSyncExternalStore(store.subscribe, store.get, store.get)
  return (
    <div data-testid="header">
      <span>{config?.title}</span>
      {config?.action}
    </div>
  )
}

function renderPage(url: string, shell: Partial<MobileShellContextValue> = {}) {
  const headerStore = createMobileHeaderStore()
  const value: MobileShellContextValue = {
    userId: 42,
    userIdStatus: 'ready',
    openCompanySwitcher: vi.fn(),
    headerStore,
    ...shell,
  }
  const utils = render(
    <MobileShellContext.Provider value={value}>
      <MemoryRouter initialEntries={[url]}>
        <HeaderProbe store={headerStore} />
        <Routes>
          <Route path="/requests" element={<RequestsMobilePage />} />
          <Route path="/requests/new" element={<div>Новая заявка (экран)</div>} />
          <Route path="/requests/:id" element={<div>Карточка заявки</div>} />
        </Routes>
        <LocationProbe />
      </MemoryRouter>
    </MobileShellContext.Provider>,
  )
  return { ...utils, shell: value }
}

const currentPath = () => screen.getByTestId('location').textContent

beforeEach(() => {
  sessionStorage.clear()
  actionItems.state = { items: [], count: 0, loading: false, error: false }
  company.value = { enabled: false, current: null }
  api.fetchCursorListPage.mockImplementation(async () => page([row(1)]))
  api.getRequestCategories.mockResolvedValue([])
  api.getRequestFormOptions.mockResolvedValue({ requester_candidates: [] })
  api.getRequestVendors.mockResolvedValue([])
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
  resetViewport()
})

describe('RequestsMobilePage — «Ждут меня»', () => {
  it('shows the requests of the current company only and opens the card', async () => {
    company.value = { enabled: true, current: 'acme' }
    actionItems.state = {
      items: [actionItem(12, 'request', 'acme'), actionItem(13, 'request', 'beta'), actionItem(5, 'invest_return', 'acme')],
      count: 3,
      loading: false,
      error: false,
    }
    const { shell } = renderPage('/requests?tab=waiting')

    const list = screen.getByRole('list', { name: 'Ждут меня' })
    expect(within(list).getAllByRole('listitem')).toHaveLength(1)
    expect(within(list).getByText('Заявка 12')).toBeInTheDocument()
    // The shared status tag (shade-8 text), not a preset «processing» tag.
    expect(within(list).getByText('На согласовании · шаг 2')).toHaveAttribute('data-tone', 'processing')
    expect(screen.queryByText('Заявка 13')).toBeNull()
    expect(screen.getByRole('button', { name: 'Ждут меня (1)' })).toHaveAttribute('aria-pressed', 'true')
    // «Ждут меня» does not ask the requests list.
    expect(api.fetchCursorListPage).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: /В других компаниях ещё 1/ }))
    expect(shell.openCompanySwitcher).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByTestId('waiting-card-12'))
    expect(currentPath()).toBe('/requests/12')
  })

  it('shows every request item on a tenant subdomain and no line about other companies', () => {
    actionItems.state = { items: [actionItem(12, 'request'), actionItem(14, 'request')], count: 2, loading: false, error: false }
    renderPage('/requests?tab=waiting')
    expect(within(screen.getByRole('list', { name: 'Ждут меня' })).getAllByRole('listitem')).toHaveLength(2)
    expect(screen.queryByText(/В других компаниях/)).toBeNull()
  })

  it('has an empty and an error state', () => {
    const { unmount } = renderPage('/requests?tab=waiting')
    expect(screen.getByText('Нет заявок, ждущих вашего решения')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Показать все заявки' }))
    expect(currentPath()).toBe('/requests?tab=all')
    unmount()

    actionItems.state = { items: [], count: 0, loading: false, error: true }
    renderPage('/requests?tab=waiting')
    fireEvent.click(screen.getByRole('button', { name: /Повторить/ }))
    expect(actionItems.refresh).toHaveBeenCalledTimes(1)
  })

  it('opens «Ждут меня» when the address names no tab', () => {
    renderPage('/requests')
    expect(currentPath()).toBe('/requests?tab=waiting')
  })
})

describe('RequestsMobilePage — cursor feed', () => {
  it('asks the list for «Все», «Мои» and «Черновики»', async () => {
    renderPage('/requests?tab=all')
    await screen.findByText('Аренда офиса 1')
    expect(requestedUrls()).toEqual(['/api/requests/?page_size=50'])

    fireEvent.click(screen.getByRole('button', { name: 'Мои' }))
    await waitFor(() => expect(requestedUrls()).toContain('/api/requests/?requester=42&page_size=50'))
    expect(currentPath()).toBe('/requests?tab=my')

    fireEvent.click(screen.getByRole('button', { name: 'Черновики' }))
    await waitFor(() => expect(requestedUrls()).toContain('/api/requests/?status=DRAFT&page_size=50'))
    expect(currentPath()).toBe('/requests?tab=drafts')
  })

  it('hides «Мои» without the user id and never sends an empty requester', async () => {
    renderPage('/requests?tab=my', { userId: null, userIdStatus: 'missing' })
    await waitFor(() => expect(currentPath()).toBe('/requests?tab=all'))
    await screen.findByText('Аренда офиса 1')
    expect(screen.queryByRole('button', { name: 'Мои' })).toBeNull()
    expect(requestedUrls().some((url) => url.includes('requester'))).toBe(false)
  })

  it('keeps «Мои» disabled while the user id is loading', () => {
    renderPage('/requests?tab=all', { userId: null, userIdStatus: 'loading' })
    expect(screen.getByRole('button', { name: 'Мои' })).toBeDisabled()
  })

  it('shows human statuses and tints a payed request without an expense', async () => {
    api.fetchCursorListPage.mockResolvedValue(
      page([row(1), row(2, { status: 'PAYED', expense_link: null }), row(3, { status: '3' })]),
    )
    renderPage('/requests?tab=all')
    const payed = await screen.findByTestId('request-card-2')
    expect(payed).toHaveClass('m-card--payed-no-expense')
    expect(within(payed).getByText('Оплачена')).toBeInTheDocument()
    expect(within(payed).getByText(/Оплачена, но расход не найден/)).toBeInTheDocument()
    const approved = screen.getByTestId('request-card-1')
    expect(approved).not.toHaveClass('m-card--payed-no-expense')
    expect(within(approved).getByText('Согласована')).toBeInTheDocument()
    expect(within(approved).getByText('ООО Альфа')).toBeInTheDocument()
    expect(within(approved).getByText(`${(2500000).toLocaleString('ru-RU').replace(/\s/g, ' ')} UZS`)).toBeInTheDocument()
    expect(within(approved).getByText(/Перечисление · ivanov/)).toBeInTheDocument()
    expect(within(screen.getByTestId('request-card-3')).getByText('На согласовании · шаг 3')).toBeInTheDocument()
    expect(approved).toHaveAttribute('href', '/requests/1')
  })

  it('shows «Загружаем ещё…» while the next page loads', async () => {
    let resolveNext: (value: unknown) => void = () => undefined
    api.fetchCursorListPage.mockImplementation((url: string) =>
      url.includes('cursor=')
        ? new Promise((resolve) => {
            resolveNext = resolve
          })
        : Promise.resolve(page([row(1)], '/api/requests/?cursor=abc')),
    )
    renderPage('/requests?tab=all')
    await screen.findByText('Аренда офиса 1')
    const more = screen.queryByRole('button', { name: 'Показать ещё' })
    if (more) fireEvent.click(more)
    expect(await screen.findByText('Загружаем ещё…')).toBeInTheDocument()
    resolveNext(page([row(2)]))
    expect(await screen.findByText('Аренда офиса 2')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText('Загружаем ещё…')).toBeNull())
  })

  it('has empty states and an error state with retry', async () => {
    api.fetchCursorListPage.mockResolvedValue(page([]))
    const first = renderPage('/requests?tab=all')
    expect(await screen.findByText('Заявок пока нет')).toBeInTheDocument()
    first.unmount()

    renderPage('/requests?tab=drafts')
    expect(await screen.findByText('Черновиков нет')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Показать все заявки' }))
    expect(currentPath()).toBe('/requests?tab=all')
  })

  it('offers to retry after an error', async () => {
    api.fetchCursorListPage.mockRejectedValueOnce(new Error('boom'))
    renderPage('/requests?tab=all')
    expect(await screen.findByText('Не удалось загрузить данные')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Повторить/ }))
    expect(await screen.findByText('Аренда офиса 1')).toBeInTheDocument()
    expect(api.fetchCursorListPage).toHaveBeenCalledTimes(2)
  })

  it('sends the typed search after a pause and clears it with «Сбросить фильтры» on an empty result', async () => {
    renderPage('/requests?tab=all')
    await screen.findByText('Аренда офиса 1')
    api.fetchCursorListPage.mockResolvedValue(page([]))
    const input = screen.getByRole('textbox', { name: 'Поиск по заявкам' })
    fireEvent.change(input, { target: { value: 'аренда' } })
    // Not sent on every keystroke: the debounce has not fired yet.
    expect(requestedUrls().some((url) => url.includes('search='))).toBe(false)
    await waitFor(() => expect(requestedUrls()).toContain('/api/requests/?search=%D0%B0%D1%80%D0%B5%D0%BD%D0%B4%D0%B0&page_size=50'))
    expect(await screen.findByText('Ничего не найдено')).toBeInTheDocument()

    api.fetchCursorListPage.mockResolvedValue(page([row(1)]))
    fireEvent.click(screen.getByRole('button', { name: 'Сбросить фильтры' }))
    expect(input).toHaveValue('')
    expect(await screen.findByText('Аренда офиса 1')).toBeInTheDocument()
    expect(requestedUrls().at(-1)).toBe('/api/requests/?page_size=50')
  })

  it('puts «Новая заявка» into the header', async () => {
    renderPage('/requests?tab=all')
    const header = screen.getByTestId('header')
    expect(within(header).getByText('Заявки')).toBeInTheDocument()
    fireEvent.click(within(header).getByRole('button', { name: 'Новая заявка' }))
    expect(currentPath()).toBe('/requests/new')
  })
})

describe('RequestsMobilePage — session', () => {
  it('restores the tab, the filters, the loaded pages and the scroll after «Назад»', async () => {
    sessionStorage.setItem(
      REQUESTS_MOBILE_SESSION_KEY,
      JSON.stringify({
        tab: 'all',
        filters: { search: '', currency: 'USD', amountMin: null, amountMax: null, amortizedOnly: false, payedMissingExpense: false },
        pagesLoaded: 2,
        scrollY: 640,
      }),
    )
    const firstPage = Array.from({ length: 50 }, (_, index) => row(index + 1))
    api.fetchCursorListPage.mockImplementation(async (url: string) =>
      url.includes('cursor=') ? page([row(51)]) : page(firstPage, '/api/requests/?cursor=next'),
    )
    renderPage('/requests')

    expect(currentPath()).toBe('/requests?tab=all')
    expect(screen.getByRole('button', { name: 'Убрать фильтр: USD' })).toBeInTheDocument()
    await screen.findByText('Аренда офиса 51')
    expect(requestedUrls()[0]).toBe('/api/requests/?currency=USD&page_size=50')
    expect(requestedUrls()).toContain('/api/requests/?cursor=next')
    await waitFor(() => expect(window.scrollTo).toHaveBeenCalledWith({ top: 640, behavior: 'auto' }))
  })

  it('does not scroll «Ждут меня» or another tab to the scroll saved for «Все»', async () => {
    sessionStorage.setItem(REQUESTS_MOBILE_SESSION_KEY, JSON.stringify({ tab: 'all', pagesLoaded: 1, scrollY: 640 }))
    actionItems.state = { items: [actionItem(12, 'request')], count: 1, loading: false, error: false }
    renderPage('/requests?tab=waiting')
    expect(within(screen.getByRole('list', { name: 'Ждут меня' })).getByText('Заявка 12')).toBeInTheDocument()

    // Coming to «Все» later is a new visit of the list, not a return from its card.
    fireEvent.click(screen.getByRole('button', { name: 'Все' }))
    await screen.findByText('Аренда офиса 1')
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20))
    })
    expect(window.scrollTo).not.toHaveBeenCalled()
  })

  it('stops loading the saved pages once the tab changes during the restore', async () => {
    sessionStorage.setItem(REQUESTS_MOBILE_SESSION_KEY, JSON.stringify({ tab: 'all', pagesLoaded: 3, scrollY: 640 }))
    // The feed's footer is far below: only the restore may ask for the next pages, not the scroll sentinel.
    const rect = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
      top: 100000,
      bottom: 100040,
      left: 0,
      right: 0,
      width: 0,
      height: 40,
      x: 0,
      y: 100000,
      toJSON: () => ({}),
    } as DOMRect)
    try {
      let resolveAll2: (value: unknown) => void = () => undefined
      let resolveDrafts: (value: unknown) => void = () => undefined
      const allPage = Array.from({ length: 50 }, (_, index) => row(index + 1))
      const draftsPage = Array.from({ length: 50 }, (_, index) => row(index + 101, { status: 'DRAFT' }))
      api.fetchCursorListPage.mockImplementation((url: string) => {
        if (url.includes('cursor=all2')) return new Promise((resolve) => (resolveAll2 = resolve))
        if (url.includes('cursor=drafts2')) return Promise.resolve(page([row(201, { status: 'DRAFT' })]))
        if (url.includes('status=DRAFT')) return new Promise((resolve) => (resolveDrafts = resolve))
        return Promise.resolve(page(allPage, '/api/requests/?cursor=all2'))
      })
      renderPage('/requests')
      await waitFor(() => expect(requestedUrls()).toContain('/api/requests/?cursor=all2'))

      fireEvent.click(screen.getByRole('button', { name: 'Черновики' }))
      await waitFor(() => expect(requestedUrls()).toContain('/api/requests/?status=DRAFT&page_size=50'))
      await act(async () => {
        resolveAll2(page([row(51)], '/api/requests/?cursor=all3'))
      })
      await act(async () => {
        resolveDrafts(page(draftsPage, '/api/requests/?cursor=drafts2'))
      })
      await screen.findByText('Аренда офиса 101')
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 20))
      })

      expect(requestedUrls()).not.toContain('/api/requests/?cursor=drafts2')
      expect(requestedUrls()).not.toContain('/api/requests/?cursor=all3')
    } finally {
      rect.mockRestore()
    }
  })

  it('makes the chips of the applied filters full-size touch targets', () => {
    sessionStorage.setItem(
      REQUESTS_MOBILE_SESSION_KEY,
      JSON.stringify({ tab: 'all', filters: { currency: 'USD' }, pagesLoaded: 1, scrollY: 0 }),
    )
    renderPage('/requests?tab=all')
    // 44 px from the mobile theme's controlHeight; a small button would be about 33 px.
    expect(screen.getByRole('button', { name: 'Убрать фильтр: USD' })).not.toHaveClass('ant-btn-sm')
  })

  it('saves the tab and the filters when leaving the feed', async () => {
    const { unmount } = renderPage('/requests?tab=all')
    await screen.findByText('Аренда офиса 1')
    fireEvent.click(screen.getByRole('button', { name: 'Черновики' }))
    unmount()
    const saved = JSON.parse(sessionStorage.getItem(REQUESTS_MOBILE_SESSION_KEY) ?? '{}')
    expect(saved.tab).toBe('drafts')
    expect(saved.filters).toMatchObject({ search: '', amortizedOnly: false })
  })

  it('ignores a malformed session', async () => {
    sessionStorage.setItem(REQUESTS_MOBILE_SESSION_KEY, '{not json')
    renderPage('/requests?tab=all')
    await screen.findByText('Аренда офиса 1')
    expect(requestedUrls()[0]).toBe('/api/requests/?page_size=50')
  })
})

describe('RequestsRoute', () => {
  it('keeps the desktop table on a desktop and the feed on a phone', async () => {
    setViewport('desktop')
    const desktop = render(
      <MemoryRouter initialEntries={['/requests']}>
        <RequestsRoute />
      </MemoryRouter>,
    )
    expect(screen.getByText('Десктопный список заявок')).toBeInTheDocument()
    desktop.unmount()

    setViewport('phone')
    render(
      <MemoryRouter initialEntries={['/requests?tab=all']}>
        <RequestsRoute />
      </MemoryRouter>,
    )
    expect(screen.queryByText('Десктопный список заявок')).toBeNull()
    expect(await screen.findByText('Аренда офиса 1')).toBeInTheDocument()
  })
})
