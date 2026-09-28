import type { ReportUnits, StatementDelta, StatementPolarity } from './reportsApi'

export type Units = ReportUnits

const DIVISOR: Record<Units, number> = { sum: 1, k: 1_000, m: 1_000_000 }
const DIGITS: Record<Units, number> = { sum: 0, k: 0, m: 1 }
const MINUS = '−'
const MONTHS_SHORT = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']

export const UNITS_LABEL: Record<Units, string> = { sum: 'сум', k: 'тыс. сум', m: 'млн сум' }
export const UNITS_SHORT: Record<Units, string> = { sum: 'сум', k: 'тыс.', m: 'млн' }
export const MONTH_NAMES = [
  'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
]

function toNumber(value: string | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function grouped(value: number, digits: number): string {
  return new Intl.NumberFormat('ru-RU', { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value)
}

function signed(value: number): string {
  return value > 0 ? '+' : value < 0 ? MINUS : ''
}

/** Amount in the chosen units: «—» for no data and for values that round to zero, «−» for negatives. */
export function formatAmount(value: string | null | undefined, units: Units): string {
  const n = toNumber(value)
  if (n === null) return '—'
  const digits = DIGITS[units]
  const factor = 10 ** digits
  const scaled = Math.round((n / DIVISOR[units]) * factor) / factor
  if (scaled === 0) return '—'
  return `${scaled < 0 ? MINUS : ''}${grouped(Math.abs(scaled), digits)}`
}

/** Exact сум amount; kopecks only when the value has them. */
export function formatExact(value: string | null | undefined): string {
  const n = toNumber(value)
  if (n === null) return '—'
  const digits = Number.isInteger(n) ? 0 : 2
  return `${n < 0 ? MINUS : ''}${grouped(Math.abs(n), digits)}`
}

export function formatRatio(value: string | null | undefined): string {
  const n = toNumber(value)
  if (n === null) return '—'
  const pct = Math.round(Math.abs(n) * 1000) / 10
  return `${n < 0 && pct > 0 ? MINUS : ''}${grouped(pct, 1)}%`
}

export type DeltaView = { text: string; direction: 'up' | 'down' | 'flat' }

function direction(value: number): DeltaView['direction'] {
  return value > 0 ? 'up' : value < 0 ? 'down' : 'flat'
}

export function formatDelta(delta: StatementDelta | undefined): DeltaView | null {
  if (!delta) return null
  if ('pp' in delta) {
    const n = toNumber(delta.pp)
    if (n === null) return null
    return { text: `${signed(n)}${grouped(Math.abs(n), 1)} п.п.`, direction: direction(n) }
  }
  const n = toNumber(delta.pct)
  if (n === null) return null
  return { text: `${signed(n)}${grouped(Math.abs(n) * 100, 1)}%`, direction: direction(n) }
}

/** Growth is good for income and results, bad for expenses; neutral lines get no verdict. */
export function isFavorable(polarity: StatementPolarity, dir: DeltaView['direction']): boolean | null {
  if (dir === 'flat' || polarity === 'neutral') return null
  const up = dir === 'up'
  return polarity === 'expense' ? !up : up
}

function lastDay(year: number, month: number): number {
  return new Date(Date.UTC(year, month, 0)).getUTCDate()
}

/** Same wording as the backend `range_label`. */
export function formatRange(from: string, to: string): string {
  if (!from || !to) return ''
  const [fy, fm] = from.split('-').map(Number)
  const [ty, tm, td] = to.split('-').map(Number)
  const mon = (m: number) => MONTHS_SHORT[m - 1]
  const fullTo = td === lastDay(ty, tm)
  if (fy === ty && fm === 1 && tm === 12 && fullTo) return String(fy)
  if (fy === ty && fm === tm) return fullTo ? `${mon(tm)} ${ty}` : `1–${td} ${mon(tm)} ${ty}`
  const end = fullTo ? mon(tm) : `${td} ${mon(tm)}`
  if (fy === ty) return `${mon(fm)} – ${end} ${ty}`
  return `${mon(fm)} ${fy} – ${end} ${ty}`
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso || iso.length < 10) return ''
  return `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}`
}
