import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Outlet } from 'react-router-dom'
import type { ReactNode } from 'react'
import { App } from './App'
import { installViewport, setViewport } from '../test/viewport'

// Routes read the breakpoint (desktop-only sections, start page): desktop unless a test switches to the phone.
installViewport('desktop')

const useAuthMock = vi.fn()
const moduleAccessState = vi.hoisted(() => ({
  value: { loading: false, hasAccess: (_key: string): boolean => true } as { loading: boolean; hasAccess: (key: string) => boolean },
}))
const setUnauthorizedHandlerMock = vi.fn()

vi.mock('../ui/auth', () => ({
  useAuth: () => useAuthMock(),
}))

vi.mock('../lib/api', () => ({
  setUnauthorizedHandler: (...args: unknown[]) => setUnauthorizedHandlerMock(...args),
}))

vi.mock('../ui/moduleAccess', () => ({
  ModuleAccessProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
  useModuleAccess: () => moduleAccessState.value,
}))

vi.mock('../ui/AppShell', () => ({
  AppShell: () => (
    <div>
      AppShell
      <Outlet />
    </div>
  ),
}))
vi.mock('../ui/LoginPage', () => ({ LoginPage: () => <div>LoginPage</div> }))
vi.mock('../ui/DashboardPage', () => ({ DashboardPage: () => <div>DashboardPage</div> }))
vi.mock('../ui/NotificationsPage', () => ({ NotificationsPage: () => <div>NotificationsPage</div> }))
vi.mock('../ui/CashPage', () => ({ CashPage: () => <div>CashPage</div> }))
vi.mock('../ui/CashSectionPage', () => ({ CashSectionPage: () => <div>CashSectionPage</div> }))
vi.mock('../ui/BankPage', () => ({ BankPage: () => <div>BankPage</div> }))
vi.mock('../ui/BankSectionPage', () => ({ BankSectionPage: () => <div>BankSectionPage</div> }))
vi.mock('../ui/BankAccountPage', () => ({ BankAccountPage: () => <div>BankAccountPage</div> }))
vi.mock('../ui/CorporateCardPage', () => ({ CorporateCardPage: () => <div>CorporateCardPage</div> }))
vi.mock('../ui/CorporateCardSectionPage', () => ({
  CorporateCardSectionPage: () => <div>CorporateCardSectionPage</div>,
}))
vi.mock('../ui/PayrollPage', () => ({ PayrollPage: () => <div>PayrollPage</div> }))
vi.mock('../ui/reports/ReportsPage', () => ({ ReportsPage: () => <div>ReportsPage</div> }))
vi.mock('../ui/ClientsDebtPage', () => ({ ClientsDebtPage: () => <div>ClientsDebtPage</div> }))
vi.mock('../ui/PayrollDocumentDetailPage', () => ({ PayrollDocumentDetailPage: () => <div>PayrollDocumentDetailPage</div> }))
vi.mock('../ui/CashExpenseDetailPage', () => ({ CashExpenseDetailPage: () => <div>CashExpenseDetailPage</div> }))
vi.mock('../ui/BankExpenseDetailPage', () => ({ BankExpenseDetailPage: () => <div>BankExpenseDetailPage</div> }))
// RequestsRoute is the real switch; the two pages it picks between are stubs.
vi.mock('../ui/requests/RequestsPage', () => ({ RequestsPage: () => <div>RequestsPage</div> }))
vi.mock('../ui/requests/RequestsMobilePage', () => ({ RequestsMobilePage: () => <div>RequestsMobilePage</div> }))
vi.mock('../ui/requests', async () => ({
  RequestsRoute: (await vi.importActual<typeof import('../ui/requests/RequestsRoute')>('../ui/requests/RequestsRoute'))
    .RequestsRoute,
  RequestCreatePage: () => <div>RequestCreatePage</div>,
  RequestDetailPage: () => <div>RequestDetailPage</div>,
  RequestFormConfigPage: () => <div>RequestFormConfigPage</div>,
  RequestApprovalConfigPage: () => <div>RequestApprovalConfigPage</div>,
  AutoRequestsConfigPage: () => <div>AutoRequestsConfigPage</div>,
  RequestMonthAuditPage: () => <div>RequestMonthAuditPage</div>,
}))
vi.mock('../ui/SettingsPage', () => ({ SettingsPage: () => <div>SettingsPage</div> }))
vi.mock('../ui/settings/TenantIntegrationConfigPage', () => ({
  TenantIntegrationConfigPage: () => <div>TenantIntegrationConfigPage</div>,
}))
vi.mock('../ui/settings/UserRolesSettingsPage', () => ({
  UserRolesSettingsPage: () => <div>UserRolesSettingsPage</div>,
}))
vi.mock('../ui/settings/CashRegistersSettingsPage', () => ({
  CashRegistersSettingsPage: () => <div>CashRegistersSettingsPage</div>,
}))
vi.mock('../ui/admin/AdminModulePage', () => ({ AdminModulePage: () => <div>AdminModulePage</div> }))
vi.mock('../ui/tg/TgWebAppLayout', () => ({
  TgWebAppLayout: () => (
    <div>
      TgWebAppLayout
      <Outlet />
    </div>
  ),
}))
vi.mock('../ui/tg/TgInvestmentsPage', () => ({ TgInvestmentsPage: () => <div>TgInvestmentsPage</div> }))
vi.mock('../ui/tg/TgRequestsPage', () => ({ TgRequestsPage: () => <div>TgRequestsPage</div> }))
vi.mock('../ui/tg/TgRequestCreatePage', () => ({ TgRequestCreatePage: () => <div>TgRequestCreatePage</div> }))
vi.mock('../ui/tg/TgRequestDetailPage', () => ({ TgRequestDetailPage: () => <div>TgRequestDetailPage</div> }))
vi.mock('../ui/tg/TgPaymentConfirmPage', () => ({ TgPaymentConfirmPage: () => <div>TgPaymentConfirmPage</div> }))

describe('App routing smoke', () => {
  beforeEach(() => {
    useAuthMock.mockReset()
    setUnauthorizedHandlerMock.mockReset()
    moduleAccessState.value = { loading: false, hasAccess: () => true }
  })

  it('renders login route when unauthenticated', () => {
    useAuthMock.mockReturnValue({ accessToken: null, logout: vi.fn() })
    render(
      <MemoryRouter initialEntries={['/login']}>
        <App />
      </MemoryRouter>,
    )
    expect(screen.getByText('LoginPage')).toBeInTheDocument()
    expect(setUnauthorizedHandlerMock).toHaveBeenCalled()
  })

  it('renders shell route when authenticated', () => {
    useAuthMock.mockReturnValue({ accessToken: 'token', logout: vi.fn() })
    render(
      <MemoryRouter initialEntries={['/reports']}>
        <App />
      </MemoryRouter>,
    )
    expect(screen.getByText('AppShell')).toBeInTheDocument()
    expect(screen.getByText('ReportsPage')).toBeInTheDocument()
  })

  it('keeps a reports address that names no card inside «Отчёты»', () => {
    useAuthMock.mockReturnValue({ accessToken: 'token', logout: vi.fn() })
    for (const url of ['/reports/classic', '/reports/classic/pnl/extra']) {
      const { unmount } = render(
        <MemoryRouter initialEntries={[url]}>
          <App />
        </MemoryRouter>,
      )
      expect(screen.getByText('Отчёт не найден')).toBeInTheDocument()
      expect(screen.getByRole('link', { name: /Все отчёты/ })).toHaveAttribute('href', '/reports')
      unmount()
    }
  })

  it('redirects the removed «Обучалка» page to requests', () => {
    useAuthMock.mockReturnValue({ accessToken: 'token', logout: vi.fn() })
    render(
      <MemoryRouter initialEntries={['/training']}>
        <App />
      </MemoryRouter>,
    )
    expect(screen.getByText('RequestsPage')).toBeInTheDocument()
  })

  it('opens a bank account page instead of the legacy bank expense redirect', () => {
    useAuthMock.mockReturnValue({ accessToken: 'token', logout: vi.fn() })
    render(
      <MemoryRouter initialEntries={['/bank/accounts/11']}>
        <App />
      </MemoryRouter>,
    )
    expect(screen.getByText('BankAccountPage')).toBeInTheDocument()
  })

  it('renders telegram layout route', () => {
    useAuthMock.mockReturnValue({ accessToken: null, logout: vi.fn() })
    render(
      <MemoryRouter initialEntries={['/tg/requests']}>
        <App />
      </MemoryRouter>,
    )
    expect(screen.getByText('TgWebAppLayout')).toBeInTheDocument()
  })

  it('redirects the removed telegram «Компании» screen to the investments landing', () => {
    useAuthMock.mockReturnValue({ accessToken: null, logout: vi.fn() })
    render(
      <MemoryRouter initialEntries={['/tg/investments/companies']}>
        <App />
      </MemoryRouter>,
    )
    expect(screen.getByText('TgInvestmentsPage')).toBeInTheDocument()
  })
})

describe('App routing on a phone', () => {
  beforeEach(() => {
    useAuthMock.mockReset()
    useAuthMock.mockReturnValue({ accessToken: 'token', logout: vi.fn() })
    setUnauthorizedHandlerMock.mockReset()
    moduleAccessState.value = { loading: false, hasAccess: () => true }
  })

  function renderAt(url: string) {
    return render(
      <MemoryRouter initialEntries={[url]}>
        <App />
      </MemoryRouter>,
    )
  }

  const DESKTOP_ONLY: Array<[string, string]> = [
    ['/cash', 'CashPage'],
    ['/settings/users-roles', 'UserRolesSettingsPage'],
    ['/requests/audit', 'RequestMonthAuditPage'],
  ]

  it('shows the desktop-only placeholder and does not mount the page', () => {
    setViewport('phone')
    for (const [url, page] of DESKTOP_ONLY) {
      const { unmount } = renderAt(url)
      expect(screen.getByText('Раздел доступен на компьютере')).toBeInTheDocument()
      expect(screen.queryByText(page)).toBeNull()
      unmount()
    }
  })

  it('opens the same sections on a desktop', () => {
    setViewport('desktop')
    for (const [url, page] of DESKTOP_ONLY) {
      const { unmount } = renderAt(url)
      expect(screen.getByText(page)).toBeInTheDocument()
      expect(screen.queryByText('Раздел доступен на компьютере')).toBeNull()
      unmount()
    }
  })

  it('keeps the requests, the request card and the create page on a phone', () => {
    setViewport('phone')
    for (const [url, page] of [
      ['/requests/12', 'RequestDetailPage'],
      ['/requests', 'RequestsMobilePage'],
      ['/requests/new', 'RequestCreatePage'],
    ]) {
      const { unmount } = renderAt(url)
      expect(screen.getByText(page)).toBeInTheDocument()
      unmount()
    }
  })

  it('starts on «Заявки → Ждут меня» on a phone', () => {
    setViewport('phone')
    renderAt('/')
    expect(screen.getByText('RequestsMobilePage')).toBeInTheDocument()
    expect(screen.queryByText('DashboardPage')).toBeNull()
  })

  it('starts on the notifications on a phone without the requests module', () => {
    setViewport('phone')
    moduleAccessState.value = { loading: false, hasAccess: (key: string) => key !== 'requests' }
    renderAt('/')
    expect(screen.getByText('NotificationsPage')).toBeInTheDocument()
  })

  it('waits for the module list before choosing the start page', () => {
    setViewport('phone')
    moduleAccessState.value = { loading: true, hasAccess: () => false }
    renderAt('/')
    expect(screen.getByRole('status', { name: 'Загрузка' })).toBeInTheDocument()
    expect(screen.queryByText('NotificationsPage')).toBeNull()
  })

  it('keeps the Mini App routes out of the portal layout at phone width', () => {
    setViewport('phone')
    for (const url of ['/tg/requests/new', '/tg/requests/12']) {
      const { unmount } = renderAt(url)
      expect(screen.getByText('TgWebAppLayout')).toBeInTheDocument()
      expect(screen.queryByText('AppShell')).toBeNull()
      expect(screen.queryByText('Раздел доступен на компьютере')).toBeNull()
      unmount()
    }
  })

  it('opens the mobile feed on a phone and the desktop table on a desktop', () => {
    setViewport('phone')
    const phone = renderAt('/requests?tab=all')
    expect(screen.getByText('RequestsMobilePage')).toBeInTheDocument()
    expect(screen.queryByText('RequestsPage')).toBeNull()
    phone.unmount()

    setViewport('desktop')
    renderAt('/requests')
    expect(screen.getByText('RequestsPage')).toBeInTheDocument()
    expect(screen.queryByText('RequestsMobilePage')).toBeNull()
  })

  it('keeps the dashboard on a desktop', () => {
    setViewport('desktop')
    renderAt('/')
    expect(screen.getByText('DashboardPage')).toBeInTheDocument()
  })
})
