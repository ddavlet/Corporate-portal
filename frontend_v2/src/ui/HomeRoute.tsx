import { Navigate } from 'react-router-dom'
import { usePortalMobileMode } from '../lib/useIsPhone'
import { DashboardPage } from './DashboardPage'

/**
 * Start page of the phone layout (also the installed app's start_url): «Уведомления» — everything waiting on the
 * user in one list (expense requests, investment payouts and investments), whatever modules the company has.
 */
export const MOBILE_HOME_PATH = '/notifications'

/** `/`: the dashboard on a desktop, the notifications on a phone. */
export function HomeRoute() {
  const isMobile = usePortalMobileMode()
  if (!isMobile) return <DashboardPage />
  return <Navigate to={MOBILE_HOME_PATH} replace />
}
