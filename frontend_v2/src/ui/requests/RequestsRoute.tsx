import { usePortalMobileMode } from '../../lib/useIsPhone'
import { RequestsMobilePage } from './RequestsMobilePage'
import { RequestsPage } from './RequestsPage'

/** `/requests`: the card feed on a phone (tab from `?tab=`), the desktop table otherwise. */
export function RequestsRoute() {
  const isMobile = usePortalMobileMode()
  return isMobile ? <RequestsMobilePage /> : <RequestsPage />
}
