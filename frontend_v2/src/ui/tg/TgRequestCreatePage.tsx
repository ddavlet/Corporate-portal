import { RequestCreatePage } from '../requests/RequestCreatePage'

/** Маршрут `/tg/requests/new` — мобильная вёрстка, настройки только здесь */
export function TgRequestCreatePage() {
  return <RequestCreatePage requestsBasePath="/tg/requests" variant="telegram" />
}
