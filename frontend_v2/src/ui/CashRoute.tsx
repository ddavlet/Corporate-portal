import { Navigate } from 'react-router-dom'

import { usePortalMobileMode } from '../lib/useIsPhone'
import { CashMobilePage } from './CashMobilePage'
import { CashPage } from './CashPage'
import { CashRegisterTransferMobilePage } from './CashRegisterTransferMobilePage'
import { CASH_PATH } from './cashMobileNav'

/**
 * `/cash` of the portal: one action («Перевести между кассами») on a phone, the desktop page otherwise. The Mini App's
 * `/tg/cash` does not go through here, and usePortalMobileMode is false under /tg/ and in Telegram WebApp anyway.
 */
export function CashRoute() {
  const isMobile = usePortalMobileMode()
  return isMobile ? <CashMobilePage /> : <CashPage />
}

/** `/cash/transfer`: the phone form; the desktop transfers in a modal on the cash pages. */
export function CashRegisterTransferRoute() {
  const isMobile = usePortalMobileMode()
  return isMobile ? <CashRegisterTransferMobilePage /> : <Navigate to={CASH_PATH} replace />
}
