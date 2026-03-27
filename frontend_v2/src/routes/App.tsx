import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from '../ui/AppShell'
import { LoginPage } from '../ui/LoginPage'
import { DashboardPage } from '../ui/DashboardPage'
import { RequestsPage } from '../ui/RequestsPage'
import { CashPage } from '../ui/CashPage'
import { BankPage } from '../ui/BankPage'
import { CorporateCardPage } from '../ui/CorporateCardPage'
import { RequestDetailPage } from '../ui/RequestDetailPage'
import { CashExpenseDetailPage } from '../ui/CashExpenseDetailPage'
import { BankExpenseDetailPage } from '../ui/BankExpenseDetailPage'
import { RequestFormConfigPage } from '../ui/RequestFormConfigPage'
import { useAuth } from '../ui/auth'

export function App() {
  const { accessToken } = useAuth()

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />

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
        <Route path="requests/:id" element={<RequestDetailPage />} />
        <Route path="cash" element={<CashPage />} />
        <Route path="cash/:id" element={<CashExpenseDetailPage />} />
        <Route path="bank" element={<BankPage />} />
        <Route path="bank/:id" element={<BankExpenseDetailPage />} />
        <Route path="corporate-card" element={<CorporateCardPage />} />
        <Route path="settings/request-form-config" element={<RequestFormConfigPage />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

