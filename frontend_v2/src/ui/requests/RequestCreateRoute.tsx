import { usePortalMobileMode } from '../../lib/useIsPhone'
import { RequestCreateMobilePage } from './RequestCreateMobilePage'
import { RequestCreatePage } from './RequestCreatePage'

/**
 * `/requests/new` of the portal: the full-screen wizard on a phone, the desktop form otherwise. The Mini App's
 * `/tg/requests/new` does not go through here (TgRequestCreatePage), and usePortalMobileMode is false under /tg/ anyway.
 */
export function RequestCreateRoute() {
  const isMobile = usePortalMobileMode()
  return isMobile ? <RequestCreateMobilePage /> : <RequestCreatePage />
}
