import { useEffect } from 'react'
import { Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import { AppShell } from '../ui/AppShell'
import { LoginPage } from '../ui/LoginPage'
import { DashboardPage } from '../ui/DashboardPage'
import { CashPage } from '../ui/CashPage'
import { BankPage } from '../ui/BankPage'
import { CorporateCardPage } from '../ui/CorporateCardPage'
import { PayrollPage } from '../ui/PayrollPage'
import { ReportsPage } from '../ui/ReportsPage'
import { InvestmentsPage } from '../ui/InvestmentsPage'
import { PublicInvestmentsSchedulePage } from '../ui/PublicInvestmentsSchedulePage'
import { ClientsDebtPage } from '../ui/ClientsDebtPage'
import { BudgetsPage } from '../ui/BudgetsPage'
import { PayrollDocumentDetailPage } from '../ui/PayrollDocumentDetailPage'
import { CashExpenseDetailPage } from '../ui/CashExpenseDetailPage'
import { BankExpenseDetailPage } from '../ui/BankExpenseDetailPage'
import {
  RequestCreatePage,
  RequestDetailPage,
  RequestFormConfigPage,
  RequestApprovalConfigPage,
  AutoRequestsConfigPage,
  RequestMonthAuditPage,
  RequestsPage,
} from '../ui/requests'
import { SettingsPage } from '../ui/SettingsPage'
import { TenantIntegrationConfigPage } from '../ui/settings/TenantIntegrationConfigPage'
import { CashRegistersSettingsPage } from '../ui/settings/CashRegistersSettingsPage'
import { InvestmentApprovalConfigPage } from '../ui/settings/InvestmentApprovalConfigPage'
import { AdminModulePage } from '../ui/admin/AdminModulePage'
import { TrainingPage } from '../ui/training/TrainingPage'
import { TgWebAppLayout } from '../ui/tg/TgWebAppLayout'
import { TgRequestsPage } from '../ui/tg/TgRequestsPage'
import { TgRequestCreatePage } from '../ui/tg/TgRequestCreatePage'
import { TgRequestDetailPage } from '../ui/tg/TgRequestDetailPage'
import { TgPaymentConfirmPage } from '../ui/tg/TgPaymentConfirmPage'
import { TgInvestmentsSchedulePage } from '../ui/tg/TgInvestmentsSchedulePage'
import { useAuth } from '../ui/auth'
import { ModuleAccessProvider } from '../ui/moduleAccess'
import { setUnauthorizedHandler } from '../lib/api'

export function App() {
  const navigate = useNavigate()
  const { accessToken, logout } = useAuth()

  useEffect(() => {
    setUnauthorizedHandler(() => {
      logout()
      navigate('/login', { replace: true })
    })
    return () => setUnauthorizedHandler(null)
  }, [logout, navigate])

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/public/investments/schedule/:token" element={<PublicInvestmentsSchedulePage />} />

      <Route path="/tg/*" element={<TgWebAppLayout />}>
        <Route index element={<Navigate to="requests" replace />} />
        <Route path="requests" element={<TgRequestsPage />} />
        <Route path="investments/schedule" element={<TgInvestmentsSchedulePage />} />
        <Route path="requests/new" element={<TgRequestCreatePage />} />
        <Route path="requests/:id" element={<TgRequestDetailPage />} />
        <Route path="payment" element={<TgPaymentConfirmPage />} />
      </Route>

      <Route
        path="/"
        element={
          accessToken ? (
            <ModuleAccessProvider>
              <AppShell />
            </ModuleAccessProvider>
          ) : (
            <Navigate to="/login" replace />
          )
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="requests" element={<RequestsPage />} />
        <Route path="requests/new" element={<RequestCreatePage />} />
        <Route path="requests/audit" element={<RequestMonthAuditPage />} />
        <Route path="requests/auto-config" element={<AutoRequestsConfigPage />} />
        <Route path="requests/:id" element={<RequestDetailPage />} />
        <Route path="cash" element={<CashPage />} />
        <Route path="cash/:id" element={<CashExpenseDetailPage />} />
        <Route path="bank" element={<BankPage />} />
        <Route path="bank/:id" element={<BankExpenseDetailPage />} />
        <Route path="corporate-card" element={<CorporateCardPage />} />
        <Route path="payroll" element={<PayrollPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="investments" element={<InvestmentsPage />} />
        <Route path="clients-debt" element={<ClientsDebtPage />} />
        <Route path="budgets" element={<BudgetsPage />} />
        <Route path="payroll/:id" element={<PayrollDocumentDetailPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="settings/request-form-config" element={<RequestFormConfigPage />} />
        <Route path="settings/request-approval-config" element={<RequestApprovalConfigPage />} />
        <Route path="settings/investment-approval-config" element={<InvestmentApprovalConfigPage />} />
        <Route path="settings/tenant-integration-config" element={<TenantIntegrationConfigPage />} />
        <Route path="settings/cash-registers" element={<CashRegistersSettingsPage />} />
        <Route path="admin" element={<AdminModulePage />} />
        <Route path="training" element={<TrainingPage />} />
      </Route>

      <Route path="*" element={<Navigate to="/requests" replace />} />
    </Routes>
  )
}

