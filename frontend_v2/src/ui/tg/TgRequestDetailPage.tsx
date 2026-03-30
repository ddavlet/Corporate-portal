import { RequestDetailPage } from '../requests/RequestDetailPage'

/** Маршрут `/tg/requests/:id` — мобильная вёрстка */
export function TgRequestDetailPage() {
  return <RequestDetailPage listPath="/tg/requests" variant="telegram" />
}
