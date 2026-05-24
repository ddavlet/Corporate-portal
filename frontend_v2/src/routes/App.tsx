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
import { ContractsPage } from '../ui/ContractsPage'
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
import { UserRolesSettingsPage } from '../ui/settings/UserRolesSettingsPage'
import { CashRegistersSettingsPage } from '../ui/settings/CashRegistersSettingsPage'
import { TelegramChatsConfigPage } from '../ui/settings/TelegramChatsConfigPage'
import { InvestmentApprovalConfigPage } from '../ui/settings/InvestmentApprovalConfigPage'
import { InvestmentProjectApprovalConfigPage } from '../ui/settings/InvestmentProjectApprovalConfigPage'
import { InvestmentFormConfigPage } from '../ui/settings/InvestmentFormConfigPage'
import { InvestmentNotificationConfigPage } from '../ui/settings/InvestmentNotificationConfigPage'
import { CashflowReportSettingsPage } from '../ui/settings/CashflowReportSettingsPage'
import { PnlReportSettingsPage } from '../ui/settings/PnlReportSettingsPage'
import { AdminRouteGate } from '../ui/admin/AdminRouteGate'
import { TrainingPage } from '../ui/training/TrainingPage'
import { TgWebAppLayout } from '../ui/tg/TgWebAppLayout'
import { TgHomePage } from '../ui/tg/TgHomePage'
import { TgRequestsPage } from '../ui/tg/TgRequestsPage'
import { TgRequestCreatePage } from '../ui/tg/TgRequestCreatePage'
import { TgRequestDetailPage } from '../ui/tg/TgRequestDetailPage'
import { TgPaymentConfirmPage } from '../ui/tg/TgPaymentConfirmPage'
import { TgInvestmentsPage } from '../ui/tg/TgInvestmentsPage'
import { TgInvestmentsCompaniesPage } from '../ui/tg/TgInvestmentsCompaniesPage'
import { TgInvestmentsProjectsPage } from '../ui/tg/TgInvestmentsProjectsPage'
import { TgInvestmentsReturnsPage } from '../ui/tg/TgInvestmentsReturnsPage'
import { TgInvestmentsSchedulePage } from '../ui/tg/TgInvestmentsSchedulePage'
import { TgInvestmentsCreatePage } from '../ui/tg/TgInvestmentsCreatePage'
import { TgCashPage } from '../ui/tg/TgCashPage'
import { TgCashListPage } from '../ui/tg/TgCashListPage'
import { TgCashExpenseDetailPage } from '../ui/tg/TgCashExpenseDetailPage'
import { TgBankPage } from '../ui/tg/TgBankPage'
import { TgBankListPage } from '../ui/tg/TgBankListPage'
import { TgBankExpenseDetailPage } from '../ui/tg/TgBankExpenseDetailPage'
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
        <Route index element={<TgHomePage />} />
        <Route path="requests" element={<TgRequestsPage />} />
        <Route path="investments" element={<TgInvestmentsPage />} />
        <Route path="investments/companies" element={<TgInvestmentsCompaniesPage />} />
        <Route path="investments/projects" element={<TgInvestmentsProjectsPage />} />
        <Route path="investments/projects/new" element={<TgInvestmentsCreatePage />} />
        <Route path="investments/schedule" element={<TgInvestmentsSchedulePage />} />
        <Route path="investments/returns" element={<TgInvestmentsReturnsPage />} />
        <Route path="requests/new" element={<TgRequestCreatePage />} />
        <Route path="requests/:id" element={<TgRequestDetailPage />} />
        <Route path="cash" element={<TgCashPage />} />
        <Route path="cash/all" element={<TgCashListPage mode="all" />} />
        <Route path="cash/expenses" element={<TgCashListPage mode="expenses" />} />
        <Route path="cash/revenues" element={<TgCashListPage mode="revenues" />} />
        <Route path="cash/expenses/:id" element={<TgCashExpenseDetailPage />} />
        <Route path="bank" element={<TgBankPage />} />
        <Route path="bank/all" element={<TgBankListPage mode="all" />} />
        <Route path="bank/expenses" element={<TgBankListPage mode="expenses" />} />
        <Route path="bank/revenues" element={<TgBankListPage mode="revenues" />} />
        <Route path="bank/expenses/:id" element={<TgBankExpenseDetailPage />} />
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
        <Route path="contracts" element={<ContractsPage />} />
        <Route path="payroll/:id" element={<PayrollDocumentDetailPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="settings/request-form-config" element={<RequestFormConfigPage />} />
        <Route path="settings/request-approval-config" element={<RequestApprovalConfigPage />} />
        <Route path="settings/investment-form-config" element={<InvestmentFormConfigPage />} />
        <Route path="settings/investment-notification-config" element={<InvestmentNotificationConfigPage />} />
        <Route path="settings/investment-approval-config" element={<InvestmentApprovalConfigPage />} />
        <Route path="settings/investment-project-approval-config" element={<InvestmentProjectApprovalConfigPage />} />
        <Route path="settings/tenant-integration-config" element={<TenantIntegrationConfigPage />} />
        <Route path="settings/users-roles" element={<UserRolesSettingsPage />} />
        <Route path="settings/cash-registers" element={<CashRegistersSettingsPage />} />
        <Route path="settings/telegram-chats" element={<TelegramChatsConfigPage />} />
        <Route path="settings/pnl-report-config" element={<PnlReportSettingsPage />} />
        <Route path="settings/cashflow-report-config" element={<CashflowReportSettingsPage />} />
        <Route path="admin" element={<AdminRouteGate />} />
        <Route path="training" element={<TrainingPage />} />
      </Route>

      <Route path="*" element={<Navigate to="/requests" replace />} />
    </Routes>
  )
}

