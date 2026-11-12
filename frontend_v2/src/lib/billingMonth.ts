import type { Dayjs } from 'dayjs'
import 'dayjs/locale/ru'
import { monthStartTashkent, nowTashkent } from './tashkentTime'

/** До 20-го включительно: прошлый, текущий и следующий календарный месяц. С 21-го: только текущий и следующий. */
export function getAllowedBillingMonthStarts(today: Dayjs = nowTashkent()): Dayjs[] {
  const current = monthStartTashkent(today)
  const previous = current.subtract(1, 'month')
  const next = current.add(1, 'month')
  const dayOfMonth = today.tz('Asia/Tashkent').date()
  if (dayOfMonth <= 20) {
    return [previous, current, next]
  }
  return [current, next]
}

export function isAllowedBillingMonth(monthStart: Dayjs, today: Dayjs = nowTashkent()): boolean {
  const key = monthStartTashkent(monthStart).format('YYYY-MM')
  return getAllowedBillingMonthStarts(today).some((m) => m.format('YYYY-MM') === key)
}

/** Если месяц недоступен по правилам на сегодня — берётся текущий календарный месяц (он всегда доступен). */
export function clampToAllowedBillingMonth(value: Dayjs, today: Dayjs = nowTashkent()): Dayjs {
  const allowed = getAllowedBillingMonthStarts(today)
  const key = monthStartTashkent(value).format('YYYY-MM')
  if (allowed.some((m) => m.format('YYYY-MM') === key)) {
    return monthStartTashkent(value)
  }
  return monthStartTashkent(today)
}

/**
 * Billing month for display, e.g. «ноябрь 2026».
 * The locale is set explicitly so the label never depends on the locale carried by the value
 * (the field showed «November 2026» in a dev build).
 */
export function formatBillingMonth(value: Dayjs): string {
  return value.locale('ru').format('MMMM YYYY')
}
