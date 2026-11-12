import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { BrowserRouter, Link, MemoryRouter, Navigate, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AppShell } from './AppShell'
import { installViewport } from '../test/viewport'
import { useMobileHeader, useMobileShell } from './mobileShell'
import { DesktopOnlyPage } from './DesktopOnlyPage'
import { captureInstallPrompt, INSTALL_PROMPT_DISMISSED_KEY, resetPwaStateForTests } from '../lib/pwa'

installViewport('phone')

const { state, logoutMock, getSettingsAccessMock } = vi.hoisted(() => ({
  state: {
    actionItemsCount: 0,
    actionItems: [] as unknown[],
    denied: new Set<string>(),
  },
  logoutMock: vi.fn(),
  getSettingsAccessMock: vi.fn(),
}))

vi.mock('../lib/useActionItems', () => ({
  useActionItems: () => ({
    items: state.actionItems,
    count: state.actionItemsCount,
    loading: false,
    error: false,
    refresh: () => Promise.resolve(),
  }),
}))

vi.mock('../lib/api', () => ({
  getSettingsAccess: () => getSettingsAccessMock(),
  changePassword: vi.fn(),
}))

vi.mock('./auth', () => ({
  useAuth: () => ({ logout: logoutMock, username: 'ivan' }),
}))

type Company = { subdomain: string; name: string; action_items_count: number }
const SUBDOMAIN_COMPANY = {
  enabled: false,
  companies: [] as Company[],
  current: null as string | null,
  currentCompany: null as Company | null,
  switchCompany: vi.fn(),
}
let companyValue = SUBDOMAIN_COMPANY

vi.mock('./company', () => ({
  useCompany: () => companyValue,
}))

vi.mock('./moduleAccess', () => ({
  useModuleAccess: () => ({ loading: false, hasAccess: (key: string) => !state.denied.has(key) }),
}))

function HeaderProbe() {
  useMobileHeader({ title: 'Заявка #12', back: '/requests' })
  return <div>Карточка заявки</div>
}

function ShellProbe() {
  const { userId, userIdStatus } = useMobileShell()
  return <div data-testid="shell-probe">{`${userIdStatus}:${userId ?? '-'}`}</div>
}

function renderShell(path = '/requests') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/" element={<AppShell />}>
          <Route path="requests" element={<ShellProbe />} />
          <Route path="requests/audit" element={<DesktopOnlyPage />} />
          <Route path="requests/:id" element={<HeaderProbe />} />
          <Route path="notifications" element={<div>Страница уведомлений</div>} />
          <Route path="settings/*" element={<DesktopOnlyPage />} />
          <Route path="cash/*" element={<DesktopOnlyPage />} />
        </Route>
        <Route path="/login" element={<div>Страница входа</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

/** The real browser history of the app (BrowserRouter): «Назад» reads its depth from history.state. */
function renderShellInBrowser(path: string) {
  window.history.replaceState(null, '', path)
  return render(
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<AppShell />}>
          <Route path="start" element={<Navigate to="/requests/12" replace />} />
          <Route path="requests" element={<ShellProbe />} />
          <Route path="requests/:id" element={<HeaderProbe />} />
          <Route
            path="notifications"
            element={
              <div>
                Страница уведомлений <Link to="/requests/12">Открыть заявку</Link>
              </div>
            }
          />
        </Route>
      </Routes>
    </BrowserRouter>,
  )
}

async function openMenu() {
  fireEvent.click(await screen.findByRole('button', { name: 'Меню' }))
  return screen.findByRole('navigation', { name: 'Разделы' })
}

function menuItem(nav: HTMLElement, name: string) {
  return within(nav)
    .queryAllByRole('menuitem')
    .find((el) => (el.textContent ?? '').includes(name))
}

describe('MobileAppShell (phone)', () => {
  beforeEach(() => {
    state.actionItemsCount = 0
    state.actionItems = []
    state.denied = new Set()
    companyValue = SUBDOMAIN_COMPANY
    logoutMock.mockReset()
    getSettingsAccessMock.mockReset()
    getSettingsAccessMock.mockResolvedValue({
      tenant_name: 'Тестовая компания',
      can_open_settings: true,
      can_open_admin: true,
      user_id: 7,
    })
  })

  it('replaces the sidebar with a header and a «Меню» drawer', async () => {
    renderShell()
    expect(await screen.findByTestId('mobile-shell')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'Заявки' })).toBeInTheDocument()

    const nav = await openMenu()
    expect(await screen.findByText('Тестовая компания')).toBeInTheDocument()
    expect(screen.getByText('ivan')).toBeInTheDocument()
    // The phone app has only «Заявки» and «Инвестиции»; the bell opens «Уведомления».
    expect(within(nav).getAllByRole('menuitem').map((el) => el.textContent)).toEqual(['Заявки', 'Инвестиции'])
    expect(within(nav).queryByText('На компьютере')).toBeNull()
    for (const name of ['Уведомления', 'Задачи', 'Касса', 'Банк', 'Корп. карта', 'Начисления ЗП', 'Отчёты', 'Договоры']) {
      expect(menuItem(nav, name), name).toBeUndefined()
    }
    expect(screen.getByRole('button', { name: /Сменить пароль/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Выйти/ })).toBeInTheDocument()
  })

  it('has no «Настройки», «Админка» or «Панель» even when the user may open them', async () => {
    renderShell()
    await waitFor(() => expect(getSettingsAccessMock).toHaveBeenCalled())
    const nav = await openMenu()
    expect(menuItem(nav, 'Настройки')).toBeUndefined()
    expect(menuItem(nav, 'Админка')).toBeUndefined()
    expect(menuItem(nav, 'Панель')).toBeUndefined()
  })

  it('hides the sections of modules the user has no access to', async () => {
    state.denied = new Set(['investments'])
    renderShell()
    const nav = await openMenu()
    expect(menuItem(nav, 'Инвестиции')).toBeUndefined()
    expect(menuItem(nav, 'Заявки')).toBeDefined()
  })

  it('shows the action count on «Заявки» and on the bell', async () => {
    state.actionItemsCount = 3
    renderShell()
    expect(await screen.findByRole('button', { name: 'Уведомления: требуется действие (3)' })).toBeInTheDocument()
    const nav = await openMenu()
    const requests = menuItem(nav, 'Заявки')!
    expect(within(requests).getByTitle('3')).toBeInTheDocument()
  })

  it('opens the notifications from the bell', async () => {
    renderShell()
    fireEvent.click(await screen.findByRole('button', { name: 'Уведомления' }))
    expect(await screen.findByText('Страница уведомлений')).toBeInTheDocument()
  })

  it('signs out from the drawer', async () => {
    renderShell()
    await openMenu()
    fireEvent.click(screen.getByRole('button', { name: /Выйти/ }))
    expect(logoutMock).toHaveBeenCalledTimes(1)
    expect(await screen.findByText('Страница входа')).toBeInTheDocument()
  })

  it('opens the password change from the drawer', async () => {
    renderShell()
    await openMenu()
    fireEvent.click(screen.getByRole('button', { name: /Сменить пароль/ }))
    await waitFor(() => expect(document.querySelector('.ant-modal-title')).toHaveTextContent('Сменить пароль'))
  })

  it('lets a page set the title and «Назад»', async () => {
    renderShell('/requests/12')
    expect(await screen.findByRole('heading', { level: 1, name: 'Заявка #12' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Меню' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Назад' }))
    // Opened directly (no earlier page in this tab): «Назад» leads to the page's fallback.
    expect(await screen.findByTestId('shell-probe')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'Заявки' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Меню' })).toBeInTheDocument()
  })

  it.each([
    ['/settings/users-roles', 'Настройки'],
    ['/requests/audit', 'Аудит месяцев'],
    ['/cash/expenses', 'Касса'],
  ])('titles the desktop-only placeholder at %s with the section name «%s»', async (path, title) => {
    renderShell(path)
    expect(await screen.findByTestId('desktop-only-page')).toBeInTheDocument()
    expect(await screen.findByRole('heading', { level: 1, name: title })).toBeInTheDocument()
  })

  describe('«Установить приложение»', () => {
    afterEach(() => {
      resetPwaStateForTests()
      window.localStorage.removeItem(INSTALL_PROMPT_DISMISSED_KEY)
    })

    it('shows the banner over the page once the browser offers the install', async () => {
      captureInstallPrompt()
      renderShell()
      await screen.findByTestId('shell-probe')
      expect(screen.queryByTestId('install-app-prompt')).toBeNull()
      const event = Object.assign(new Event('beforeinstallprompt', { cancelable: true }), {
        prompt: vi.fn().mockResolvedValue(undefined),
        userChoice: Promise.resolve({ outcome: 'dismissed' as const }),
      })
      act(() => {
        window.dispatchEvent(event)
      })
      const banner = await screen.findByRole('region', { name: 'Установить приложение' })
      expect(within(screen.getByRole('main')).getByTestId('install-app-prompt')).toBe(banner)
      fireEvent.click(within(banner).getByRole('button', { name: 'Установить' }))
      await waitFor(() => expect(event.prompt).toHaveBeenCalledTimes(1))
    })
  })

  describe('«Назад» in the browser history', () => {
    afterEach(() => {
      window.history.replaceState(null, '', '/')
    })

    it('leads to the fallback when the page was reached by <Navigate replace> (first entry of the tab)', async () => {
      renderShellInBrowser('/start')
      expect(await screen.findByRole('heading', { level: 1, name: 'Заявка #12' })).toBeInTheDocument()
      expect(window.location.pathname).toBe('/requests/12')
      fireEvent.click(screen.getByRole('button', { name: 'Назад' }))
      // navigate(-1) would leave the portal here; the page's fallback opens instead, in place of the current entry.
      expect(await screen.findByTestId('shell-probe')).toBeInTheDocument()
      expect(window.location.pathname).toBe('/requests')
      expect((window.history.state as { idx?: number } | null)?.idx).toBe(0)
    })

    it('goes back to the earlier page of the portal when there is one', async () => {
      renderShellInBrowser('/notifications')
      fireEvent.click(await screen.findByRole('link', { name: 'Открыть заявку' }))
      expect(await screen.findByRole('heading', { level: 1, name: 'Заявка #12' })).toBeInTheDocument()
      fireEvent.click(screen.getByRole('button', { name: 'Назад' }))
      // History back, not the fallback /requests.
      expect(await screen.findByText(/Страница уведомлений/)).toBeInTheDocument()
      expect(window.location.pathname).toBe('/notifications')
    })
  })

  it('passes the user id to the pages', async () => {
    renderShell()
    await waitFor(() => expect(screen.getByTestId('shell-probe')).toHaveTextContent('ready:7'))
  })

  it('reports a missing user id when the answer has none', async () => {
    getSettingsAccessMock.mockResolvedValue({ tenant_name: 'Тестовая компания', can_open_settings: false, can_open_admin: false })
    renderShell()
    await waitFor(() => expect(screen.getByTestId('shell-probe')).toHaveTextContent('missing:-'))
  })

  it('reports a missing user id when the request fails', async () => {
    getSettingsAccessMock.mockRejectedValue(new Error('403'))
    renderShell()
    await waitFor(() => expect(screen.getByTestId('shell-probe')).toHaveTextContent('missing:-'))
  })

  it('has no company switcher on a tenant subdomain', async () => {
    renderShell()
    await screen.findByTestId('mobile-shell')
    expect(screen.queryByRole('combobox', { name: /Компания/ })).toBeNull()
  })

  it('shows the compact company switcher on the shared app host', async () => {
    const alpha = { subdomain: 'alpha', name: 'Альфа', action_items_count: 0 }
    companyValue = {
      ...SUBDOMAIN_COMPANY,
      enabled: true,
      companies: [alpha, { subdomain: 'beta', name: 'Бета', action_items_count: 2 }],
      current: 'alpha',
      currentCompany: alpha,
    }
    state.actionItems = [
      { kind: 'request', id: 1, tenant: { subdomain: 'beta', name: 'Бета' } },
      { kind: 'request', id: 2, tenant: { subdomain: 'beta', name: 'Бета' } },
    ]
    state.actionItemsCount = 2
    renderShell()
    const header = await screen.findByRole('banner')
    expect(await within(header).findByRole('combobox', { name: /Компания/ })).toBeInTheDocument()
    expect(within(screen.getByTestId('company-switcher-other-badge')).getByTitle('2')).toBeInTheDocument()
  })
})
