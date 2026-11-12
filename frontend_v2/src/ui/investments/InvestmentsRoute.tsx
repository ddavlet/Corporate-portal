import { Navigate } from 'react-router-dom'

import { usePortalMobileMode } from '../../lib/useIsPhone'
import { InvestmentsPage } from '../InvestmentsPage'
import { InvestmentCollectMobilePage } from './InvestmentCollectMobilePage'
import { InvestmentCreateMobilePage } from './InvestmentCreateMobilePage'
import { InvestmentsMobilePage } from './InvestmentsMobilePage'
import { InvestReturnCreateMobilePage } from './InvestReturnCreateMobilePage'
import { INVESTMENTS_PATH } from './investmentsMobileNav'

/**
 * `/investments` of the portal: two actions on a phone, the desktop tabs otherwise. The Mini App's `/tg/investments`
 * does not go through here, and usePortalMobileMode is false under /tg/ and in Telegram WebApp anyway.
 */
export function InvestmentsRoute() {
  const isMobile = usePortalMobileMode()
  return isMobile ? <InvestmentsMobilePage /> : <InvestmentsPage />
}

/** `/investments/returns/new`: the phone form; the desktop creates a payout in a modal on `/investments`. */
export function InvestReturnCreateRoute() {
  const isMobile = usePortalMobileMode()
  return isMobile ? <InvestReturnCreateMobilePage /> : <Navigate to={INVESTMENTS_PATH} replace />
}

/** `/investments/collect`: the phone wizard; the desktop collects in a modal on `/investments`. */
export function InvestmentCollectRoute() {
  const isMobile = usePortalMobileMode()
  return isMobile ? <InvestmentCollectMobilePage /> : <Navigate to={INVESTMENTS_PATH} replace />
}

/** `/investments/new`: the phone «Подать заявку на вложение»; the desktop opens it in a modal on `/investments`. */
export function InvestmentCreateRoute() {
  const isMobile = usePortalMobileMode()
  return isMobile ? <InvestmentCreateMobilePage /> : <Navigate to={INVESTMENTS_PATH} replace />
}
