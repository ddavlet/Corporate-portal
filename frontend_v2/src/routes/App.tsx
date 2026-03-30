import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from '../ui/AppShell'
import { LoginPage } from '../ui/LoginPage'
import { DashboardPage } from '../ui/DashboardPage'
import { CashPage } from '../ui/CashPage'
import { BankPage } from '../ui/BankPage'
import { CorporateCardPage } from '../ui/CorporateCardPage'
import { PayrollPage } from '../ui/PayrollPage'
import { PayrollDocumentDetailPage } from '../ui/PayrollDocumentDetailPage'
import { CashExpenseDetailPage } from '../ui/CashExpenseDetailPage'
import { BankExpenseDetailPage } from '../ui/BankExpenseDetailPage'
import {
  RequestCreatePage,
  RequestDetailPage,
  RequestFormConfigPage,
  RequestApprovalConfigPage,
  RequestsPage,
} from '../ui/requests'
import { SettingsPage } from '../ui/SettingsPage'
import { TgWebAppLayout } from '../ui/tg/TgWebAppLayout'
import { TgRequestsPage } from '../ui/tg/TgRequestsPage'
import { TgRequestCreatePage } from '../ui/tg/TgRequestCreatePage'
import { TgRequestDetailPage } from '../ui/tg/TgRequestDetailPage'
import { useAuth } from '../ui/auth'

export function App() {
  const { accessToken } = useAuth()

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />

      <Route path="/tg/*" element={<TgWebAppLayout />}>
        <Route index element={<Navigate to="requests" replace />} />
        <Route path="requests" element={<TgRequestsPage />} />
        <Route path="requests/new" element={<TgRequestCreatePage />} />
        <Route path="requests/:id" element={<TgRequestDetailPage />} />
      </Route>

      <Route
        path="/"
        element={
          accessToken ? (
            <AppShell />
          ) : (
            <Navigate to="/login" replace />
          )
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="requests" element={<RequestsPage />} />
        <Route path="requests/new" element={<RequestCreatePage />} />
        <Route path="requests/:id" element={<RequestDetailPage />} />
        <Route path="cash" element={<CashPage />} />
        <Route path="cash/:id" element={<CashExpenseDetailPage />} />
        <Route path="bank" element={<BankPage />} />
        <Route path="bank/:id" element={<BankExpenseDetailPage />} />
        <Route path="corporate-card" element={<CorporateCardPage />} />
        <Route path="payroll" element={<PayrollPage />} />
        <Route path="payroll/:id" element={<PayrollDocumentDetailPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="settings/request-form-config" element={<RequestFormConfigPage />} />
        <Route path="settings/request-approval-config" element={<RequestApprovalConfigPage />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

