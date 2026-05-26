import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Outlet } from 'react-router-dom'
import type { ReactNode } from 'react'
import { App } from './App'

const useAuthMock = vi.fn()
const setUnauthorizedHandlerMock = vi.fn()

vi.mock('../ui/auth', () => ({
  useAuth: () => useAuthMock(),
}))

vi.mock('../lib/api', () => ({
  setUnauthorizedHandler: (...args: unknown[]) => setUnauthorizedHandlerMock(...args),
}))

vi.mock('../ui/moduleAccess', () => ({
  ModuleAccessProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
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
vi.mock('../ui/CashPage', () => ({ CashPage: () => <div>CashPage</div> }))
vi.mock('../ui/CashSectionPage', () => ({ CashSectionPage: () => <div>CashSectionPage</div> }))
vi.mock('../ui/BankPage', () => ({ BankPage: () => <div>BankPage</div> }))
vi.mock('../ui/BankSectionPage', () => ({ BankSectionPage: () => <div>BankSectionPage</div> }))
vi.mock('../ui/CorporateCardPage', () => ({ CorporateCardPage: () => <div>CorporateCardPage</div> }))
vi.mock('../ui/CorporateCardSectionPage', () => ({
  CorporateCardSectionPage: () => <div>CorporateCardSectionPage</div>,
}))
vi.mock('../ui/PayrollPage', () => ({ PayrollPage: () => <div>PayrollPage</div> }))
vi.mock('../ui/ReportsPage', () => ({ ReportsPage: () => <div>ReportsPage</div> }))
vi.mock('../ui/ClientsDebtPage', () => ({ ClientsDebtPage: () => <div>ClientsDebtPage</div> }))
vi.mock('../ui/PayrollDocumentDetailPage', () => ({ PayrollDocumentDetailPage: () => <div>PayrollDocumentDetailPage</div> }))
vi.mock('../ui/CashExpenseDetailPage', () => ({ CashExpenseDetailPage: () => <div>CashExpenseDetailPage</div> }))
vi.mock('../ui/BankExpenseDetailPage', () => ({ BankExpenseDetailPage: () => <div>BankExpenseDetailPage</div> }))
vi.mock('../ui/requests', () => ({
  RequestCreatePage: () => <div>RequestCreatePage</div>,
  RequestDetailPage: () => <div>RequestDetailPage</div>,
  RequestFormConfigPage: () => <div>RequestFormConfigPage</div>,
  RequestApprovalConfigPage: () => <div>RequestApprovalConfigPage</div>,
  AutoRequestsConfigPage: () => <div>AutoRequestsConfigPage</div>,
  RequestMonthAuditPage: () => <div>RequestMonthAuditPage</div>,
  RequestsPage: () => <div>RequestsPage</div>,
}))
vi.mock('../ui/SettingsPage', () => ({ SettingsPage: () => <div>SettingsPage</div> }))
vi.mock('../ui/settings/TenantIntegrationConfigPage', () => ({
  TenantIntegrationConfigPage: () => <div>TenantIntegrationConfigPage</div>,
}))
vi.mock('../ui/settings/CashRegistersSettingsPage', () => ({
  CashRegistersSettingsPage: () => <div>CashRegistersSettingsPage</div>,
}))
vi.mock('../ui/admin/AdminModulePage', () => ({ AdminModulePage: () => <div>AdminModulePage</div> }))
vi.mock('../ui/training/TrainingPage', () => ({ TrainingPage: () => <div>TrainingPage</div> }))
vi.mock('../ui/tg/TgWebAppLayout', () => ({ TgWebAppLayout: () => <div>TgWebAppLayout</div> }))
vi.mock('../ui/tg/TgRequestsPage', () => ({ TgRequestsPage: () => <div>TgRequestsPage</div> }))
vi.mock('../ui/tg/TgRequestCreatePage', () => ({ TgRequestCreatePage: () => <div>TgRequestCreatePage</div> }))
vi.mock('../ui/tg/TgRequestDetailPage', () => ({ TgRequestDetailPage: () => <div>TgRequestDetailPage</div> }))
vi.mock('../ui/tg/TgPaymentConfirmPage', () => ({ TgPaymentConfirmPage: () => <div>TgPaymentConfirmPage</div> }))

describe('App routing smoke', () => {
  beforeEach(() => {
    useAuthMock.mockReset()
    setUnauthorizedHandlerMock.mockReset()
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

  it('renders telegram layout route', () => {
    useAuthMock.mockReturnValue({ accessToken: null, logout: vi.fn() })
    render(
      <MemoryRouter initialEntries={['/tg/requests']}>
        <App />
      </MemoryRouter>,
    )
    expect(screen.getByText('TgWebAppLayout')).toBeInTheDocument()
  })
})
