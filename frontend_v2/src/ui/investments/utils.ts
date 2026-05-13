import type { InvestCompanyRow } from '../../lib/api'

export type CompanyFilter = 'all' | 'none' | number
export type SchedulePaidFilter = 'all' | 'paid' | 'unpaid'

const moneyFmt = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })

export function asMoney(value: string | number): string {
  const n = typeof value === 'number' ? value : Number(String(value).replace(',', '.'))
  return Number.isFinite(n) ? moneyFmt.format(n) : '0'
}

export function asNumber(value: string | number): number {
  const n = typeof value === 'number' ? value : Number(String(value).replace(',', '.'))
  return Number.isFinite(n) ? n : 0
}

export function dateText(value: string): string {
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value || '-'
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    timeZone: 'Asia/Tashkent',
  }).format(d)
}

export function byCompany<T extends { company: number | null }>(rows: T[], filter: CompanyFilter): T[] {
  if (filter === 'all') return rows
  if (filter === 'none') return rows.filter((r) => r.company == null)
  return rows.filter((r) => r.company === filter)
}

export function inDateRange<T>(rows: T[], dateField: keyof T, from?: string, to?: string): T[] {
  if (!from && !to) return rows
  return rows.filter((r) => {
    const raw = r[dateField] as unknown as string
    const v = String(raw || '').slice(0, 10)
    if (!v) return false
    if (from && v < from) return false
    if (to && v > to) return false
    return true
  })
}

export function buildCompanyMap(companies: InvestCompanyRow[]): Map<number, string> {
  return new Map(companies.map((c) => [c.id, c.name]))
}

export function makeCompanyLabel(map: Map<number, string>) {
  return (id: number | null): string => {
    if (id == null) return 'Без компании'
    return map.get(id) || `#${id}`
  }
}

export function makeCompanyOptions(companies: InvestCompanyRow[]) {
  return [
    { label: 'Все компании', value: 'all' as const },
    { label: 'Без компании', value: 'none' as const },
    ...companies.map((c) => ({ label: c.name, value: c.id })),
  ]
}

export function makeCompanySelectOptions(companies: InvestCompanyRow[]) {
  return companies.map((c) => ({ value: c.id, label: c.name }))
}

export type CurrencyTotal = { currency: string; total: number }

export function totalsByCurrency<T extends { currency: string }>(
  rows: T[],
  amountField: keyof T,
): CurrencyTotal[] {
  const map = new Map<string, number>()
  for (const r of rows) {
    const cur = r.currency || '—'
    const v = asNumber(r[amountField] as unknown as string | number)
    map.set(cur, (map.get(cur) || 0) + v)
  }
  return Array.from(map.entries())
    .map(([currency, total]) => ({ currency, total }))
    .sort((a, b) => a.currency.localeCompare(b.currency))
}

export const CURRENCY_OPTIONS = [
  { value: 'USD', label: 'USD' },
  { value: 'EUR', label: 'EUR' },
  { value: 'UZS', label: 'UZS' },
]

/** Валюты для возвратов инвестиций (только USD / UZS). */
export const RETURN_CURRENCY_OPTIONS = [
  { value: 'USD', label: 'USD' },
  { value: 'UZS', label: 'UZS' },
]

export function precisionFor(currency: string | undefined): 0 | 2 {
  return (currency || '').toUpperCase() === 'UZS' ? 0 : 2
}

export function clampDayToMonth(year: number, monthIndex: number, day: number): Date {
  const lastDay = new Date(year, monthIndex + 1, 0).getDate()
  const safeDay = Math.min(day, lastDay)
  return new Date(year, monthIndex, safeDay)
}

export function generateSeriesDates(startYear: number, startMonthIndex: number, day: number, count: number): Date[] {
  const out: Date[] = []
  for (let i = 0; i < count; i++) {
    const y = startYear + Math.floor((startMonthIndex + i) / 12)
    const m = (startMonthIndex + i) % 12
    out.push(clampDayToMonth(y, m, day))
  }
  return out
}

export function isoDate(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}
