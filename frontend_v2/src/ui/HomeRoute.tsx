import { Navigate } from 'react-router-dom'
import { usePortalMobileMode } from '../lib/useIsPhone'
import { useModuleAccess } from './moduleAccess'
import { DashboardPage } from './DashboardPage'
import { MobileStateWidget } from './MobileStateWidget'

/** Start page of the phone layout (also the installed app's start_url): «Заявки → Ждут меня». */
export const MOBILE_HOME_PATH = '/requests?tab=waiting'

/**
 * `/`: the dashboard on a desktop. On a phone it opens the requests waiting on the user, or the notifications when the
 * company has no requests module.
 */
export function HomeRoute() {
  const isMobile = usePortalMobileMode()
  const { loading, hasAccess } = useModuleAccess()
  if (!isMobile) return <DashboardPage />
  // Until the module list arrives every module reads as switched off: wait instead of sending the user elsewhere.
  if (loading) return <MobileStateWidget state="loading" />
  return <Navigate to={hasAccess('requests') ? MOBILE_HOME_PATH : '/notifications'} replace />
}
