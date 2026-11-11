import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { NotificationsPage } from './NotificationsPage'
import { CompanyProvider, useCompany } from './company'

type HookState = {
  items: unknown[]
  count: number
  loading: boolean
  error: boolean
  refresh: () => Promise<void>
}

const refreshMock = vi.fn(() => Promise.resolve())
let hookState: HookState

vi.mock('../lib/useActionItems', () => ({
  useActionItems: () => hookState,
  resetActionItemsCache: vi.fn(),
}))

const { portalState, getMyCompaniesMock } = vi.hoisted(() => ({
  portalState: { shared: false },
  getMyCompaniesMock: vi.fn(),
}))

vi.mock('../lib/portalMode', () => ({ isSharedAppMode: () => portalState.shared }))
vi.mock('../lib/myCompaniesApi', () => ({ getMyCompanies: () => getMyCompaniesMock() }))
vi.mock('./auth', () => ({ useAuth: () => ({ logout: vi.fn() }) }))

const ITEMS = [
  {
    kind: 'request',
    id: 12,
    approval_id: 120,
    step: 2,
    step_type: 'serial',
    title: 'Оплата аренды',
    amount: '1500000.00',
    currency: 'UZS',
    type_code: 'bank',
    type_label: 'Перечисление',
    created_at: '2026-11-10T10:00:00Z',
    link: '/requests/12',
  },
  {
    kind: 'invest_return',
    id: 5,
    approval_id: 50,
    step: 1,
    step_type: 'serial',
    title: 'Выплата инвестиции #5',
    amount: '2500.00',
    currency: 'USD',
    type_code: 'dividends',
    type_label: 'Дивиденды',
    created_at: '2026-11-09T10:00:00Z',
    link: '/investments?tab=returns&open=5',
  },
  {
    kind: 'project_investment',
    id: 8,
    approval_id: 80,
    step: 1,
    step_type: 'confirmation',
    title: 'Вложение в проект #8',
    amount: '1000.00',
    currency: 'USD',
    type_code: '',
    type_label: '',
    created_at: '2026-11-08T10:00:00Z',
    link: '/investments?tab=investments&open=8',
  },
]

/** Parses rgb()/rgba()/#rrggbb and composites it over `under` (white by default). */
function parseColor(value: string, under: [number, number, number] = [255, 255, 255]): [number, number, number] {
  const hex = value.match(/^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i)
  if (hex) return [parseInt(hex[1], 16), parseInt(hex[2], 16), parseInt(hex[3], 16)]
  const m = value.match(/rgba?\(([^)]+)\)/)
  if (!m) throw new Error(`Unparsed colour: "${value}"`)
  const [r, g, b, a = 1] = m[1].split(',').map((part) => Number(part.trim()))
  return [r, g, b].map((c, i) => c * a + under[i] * (1 - a)) as [number, number, number]
}

function luminance([r, g, b]: [number, number, number]): number {
  const lin = (c: number) => {
    const v = c / 255
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
}

function contrastOf(element: HTMLElement): number {
  const style = getComputedStyle(element)
  const background = style.backgroundColor && style.backgroundColor !== 'rgba(0, 0, 0, 0)' ? style.backgroundColor : '#ffffff'
  const bg = parseColor(background)
  const fg = parseColor(style.color, bg)
  const [hi, lo] = [luminance(fg), luminance(bg)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="location">{`${location.pathname}${location.search}`}</div>
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/notifications']}>
      <Routes>
        <Route path="/notifications" element={<NotificationsPage />} />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('NotificationsPage', () => {
  beforeEach(() => {
    refreshMock.mockClear()
    hookState = { items: [], count: 0, loading: false, error: false, refresh: refreshMock }
  })

  it('lists requests and both kinds of investments with amount, step and kind', () => {
    hookState = { ...hookState, items: ITEMS, count: 3 }
    renderPage()
    expect(screen.getByText('Требуется ваше действие: 3')).toBeInTheDocument()
    expect(screen.getByText('Заявка')).toBeInTheDocument()
    expect(screen.getByText('Выплата инвестиции')).toBeInTheDocument()
    expect(screen.getByText('Вложение в проект')).toBeInTheDocument()
    expect(screen.getByText('Оплата аренды')).toBeInTheDocument()
    expect(screen.getByText('Шаг 2: согласование')).toBeInTheDocument()
    expect(screen.getByText('Шаг 1: подтверждение')).toBeInTheDocument()
    expect(screen.getByText(/2\s500\s+USD/)).toBeInTheDocument()
    expect(screen.getAllByText('Решение принимается в Telegram')).toHaveLength(2)
    expect(screen.getAllByRole('link')).toHaveLength(3)
  })

  it('labels the date as the creation date', () => {
    hookState = { ...hookState, items: ITEMS, count: 3 }
    renderPage()
    expect(screen.getByText('Создана 10.11.2026')).toBeInTheDocument()
  })

  it('kind tags and supporting text reach 4.5:1 contrast', () => {
    hookState = { ...hookState, items: ITEMS, count: 3 }
    renderPage()
    for (const label of ['Заявка', 'Выплата инвестиции', 'Вложение в проект']) {
      expect(contrastOf(screen.getByText(label))).toBeGreaterThanOrEqual(4.5)
    }
    for (const text of ['Шаг 2: согласование', 'Перечисление', 'Создана 10.11.2026', 'Требуется ваше действие: 3']) {
      expect(contrastOf(screen.getByText(text))).toBeGreaterThanOrEqual(4.5)
    }
    for (const note of screen.getAllByText('Решение принимается в Telegram')) {
      expect(contrastOf(note)).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('opens the request card on click', async () => {
    hookState = { ...hookState, items: ITEMS, count: 3 }
    renderPage()
    await userEvent.click(screen.getByRole('link', { name: /Оплата аренды/ }))
    expect(screen.getByTestId('location')).toHaveTextContent('/requests/12')
  })

  it('opens the investment return card on click', async () => {
    hookState = { ...hookState, items: ITEMS, count: 3 }
    renderPage()
    await userEvent.click(screen.getByRole('link', { name: /Выплата инвестиции #5/ }))
    expect(screen.getByTestId('location')).toHaveTextContent('/investments?tab=returns&open=5')
  })

  it('shows an empty state', () => {
    renderPage()
    expect(screen.getByText('Сейчас ничего не ждёт вашего действия')).toBeInTheDocument()
    expect(screen.queryAllByRole('link')).toHaveLength(0)
  })

  it('shows an error with a retry button', async () => {
    hookState = { ...hookState, error: true }
    renderPage()
    expect(screen.getByText('Не удалось загрузить уведомления')).toBeInTheDocument()
    expect(screen.queryByText('Сейчас ничего не ждёт вашего действия')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Повторить/ }))
    expect(refreshMock).toHaveBeenCalledTimes(1)
  })
})

describe('NotificationsPage on the shared app host (crit. 19)', () => {
  const SHARED_ITEMS = [
    {
      ...ITEMS[0],
      id: 77,
      title: 'Закуп в Бете',
      link: '/requests/77?company=beta',
      tenant: { subdomain: 'beta', name: 'Бета' },
    },
    {
      ...ITEMS[0],
      id: 12,
      title: 'Аренда в Альфе',
      link: '/requests/12?company=alpha',
      tenant: { subdomain: 'alpha', name: 'Альфа' },
    },
  ]

  function CompanyProbe() {
    const { current } = useCompany()
    return <div data-testid="company">{current}</div>
  }

  function renderShared() {
    return render(
      <MemoryRouter initialEntries={['/notifications']}>
        <CompanyProvider>
          <Routes>
            <Route path="/notifications" element={<NotificationsPage />} />
            <Route
              path="*"
              element={
                <>
                  <LocationProbe />
                  <CompanyProbe />
                </>
              }
            />
          </Routes>
        </CompanyProvider>
      </MemoryRouter>,
    )
  }

  beforeEach(() => {
    portalState.shared = true
    sessionStorage.clear()
    localStorage.clear()
    sessionStorage.setItem('kolberg_v2_company', 'alpha')
    getMyCompaniesMock.mockReset()
    getMyCompaniesMock.mockResolvedValue([
      { subdomain: 'alpha', name: 'Альфа', action_items_count: 1 },
      { subdomain: 'beta', name: 'Бета', action_items_count: 1 },
    ])
    hookState = { items: SHARED_ITEMS, count: 2, loading: false, error: false, refresh: refreshMock }
  })

  afterEach(() => {
    portalState.shared = false
  })

  it('shows the total and the company of each item', async () => {
    renderShared()
    expect(await screen.findByText('Требуется ваше действие: 2')).toBeInTheDocument()
    expect(screen.getByText('Бета')).toBeInTheDocument()
    expect(screen.getByText('Альфа')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Закуп в Бете/ })).toHaveAttribute('data-action-item', 'beta:request-77')
  })

  it('switches to the item company and opens the object on click', async () => {
    renderShared()
    await userEvent.click(await screen.findByRole('link', { name: /Закуп в Бете/ }))
    expect(await screen.findByTestId('location')).toHaveTextContent(/^\/requests\/77$/)
    expect(screen.getByTestId('company')).toHaveTextContent('beta')
    expect(sessionStorage.getItem('kolberg_v2_company')).toBe('beta')
  })
})
