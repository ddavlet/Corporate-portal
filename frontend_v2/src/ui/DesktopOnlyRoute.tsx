import { Outlet } from 'react-router-dom'
import { usePortalMobileMode } from '../lib/useIsPhone'
import { DesktopOnlyPage } from './DesktopOnlyPage'

/**
 * Layout route of the sections that have no phone layout yet: on a phone the placeholder is shown and the page is not
 * mounted (it asks the server for nothing); on a desktop the page opens as before.
 */
export function DesktopOnlyRoute() {
  const isMobile = usePortalMobileMode()
  return isMobile ? <DesktopOnlyPage /> : <Outlet />
}
