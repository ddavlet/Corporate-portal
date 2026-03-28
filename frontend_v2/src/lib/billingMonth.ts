import type { Dayjs } from 'dayjs'
import dayjs from 'dayjs'

/** До 20-го включительно: прошлый, текущий и следующий календарный месяц. С 21-го: только текущий и следующий. */
export function getAllowedBillingMonthStarts(today: Dayjs = dayjs()): Dayjs[] {
  const current = today.startOf('month')
  const previous = current.subtract(1, 'month')
  const next = current.add(1, 'month')
  const dayOfMonth = today.date()
  if (dayOfMonth <= 20) {
    return [previous, current, next]
  }
  return [current, next]
}

export function isAllowedBillingMonth(monthStart: Dayjs, today: Dayjs = dayjs()): boolean {
  const key = monthStart.startOf('month').format('YYYY-MM')
  return getAllowedBillingMonthStarts(today).some((m) => m.format('YYYY-MM') === key)
}

/** Если месяц недоступен по правилам на сегодня — берётся текущий календарный месяц (он всегда доступен). */
export function clampToAllowedBillingMonth(value: Dayjs, today: Dayjs = dayjs()): Dayjs {
  const allowed = getAllowedBillingMonthStarts(today)
  const key = value.startOf('month').format('YYYY-MM')
  if (allowed.some((m) => m.format('YYYY-MM') === key)) {
    return value.startOf('month')
  }
  return today.startOf('month')
}
