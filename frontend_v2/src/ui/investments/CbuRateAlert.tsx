import { Alert } from 'antd'

import { dateText, staleCbuRateDate } from './utils'

type Props = {
  rows: { date: string; rate_date?: string | null }[]
  /** Сегодня (YYYY-MM-DD) — для тестов; по умолчанию дата по Ташкенту. */
  todayIso?: string
}

/** Предупреждение над итогами, если хоть одна строка выборки посчитана не по курсу ЦБ на свою дату. */
export function CbuRateAlert({ rows, todayIso }: Props) {
  const rateDate = staleCbuRateDate(rows, todayIso)
  if (!rateDate) return null
  return (
    <Alert
      type="warning"
      showIcon
      message={`Курс ЦБ может быть неактуален: нет связи с источником. Суммы в USD/UZS посчитаны по последнему загруженному курсу (на ${dateText(rateDate)}).`}
    />
  )
}
