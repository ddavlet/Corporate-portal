import type { FundingPoolRequestDto } from '../../lib/api'

const DESCRIPTION_LIMIT = 80

export type FundingMethod = 'cash' | 'bank_transfer'

export const FUNDING_METHOD_LABELS: Record<FundingMethod, string> = {
  cash: 'Наличными',
  bank_transfer: 'Переводом на счёт',
}

export function fundingMethodLabel(value: string | null | undefined): string {
  if (value === 'cash' || value === 'bank_transfer') return FUNDING_METHOD_LABELS[value]
  return 'не указан'
}

export type CurrencyTotal = { currency: string; amount: number; count: number }

function toNumber(value: string | number): number {
  const n = typeof value === 'number' ? value : Number(String(value).replace(',', '.'))
  return Number.isFinite(n) ? n : 0
}

/** Итоги по валютам выбранных заявок; порядок валют — по первому появлению. */
export function totalsByCurrency(rows: FundingPoolRequestDto[], selectedIds: Set<number>): CurrencyTotal[] {
  const map = new Map<string, CurrencyTotal>()
  for (const row of rows) {
    if (!selectedIds.has(row.id)) continue
    const item = map.get(row.currency) ?? { currency: row.currency, amount: 0, count: 0 }
    item.amount += toNumber(row.amount)
    item.count += 1
    map.set(row.currency, item)
  }
  return Array.from(map.values())
}

function requestNote(row: FundingPoolRequestDto): string {
  if (row.kind === 'transfer') return 'перевод между кассами'
  const text = (row.description || '').trim() || (row.payment_purpose || '').trim()
  return Array.from(text.split(/\s+/).filter(Boolean).join(' ')).slice(0, DESCRIPTION_LIMIT).join('')
}

/** Тот же формат, что backend `build_default_comment`. */
export function defaultCollectComment(rows: FundingPoolRequestDto[]): string {
  if (rows.length === 0) return ''
  const numbers = rows.map((r) => `№${r.id}`).join(', ')
  const head = rows.length === 1 ? `На основании заявки ${numbers}.` : `На основании заявок ${numbers}.`
  const notes = rows.flatMap((r) => {
    const note = requestNote(r)
    return note ? [`№${r.id} — ${note}`] : []
  })
  return notes.length ? `${head} ${notes.join('; ')}` : head
}

export function groupByKind(rows: FundingPoolRequestDto[]): {
  expense: FundingPoolRequestDto[]
  transfer: FundingPoolRequestDto[]
} {
  return {
    expense: rows.filter((r) => r.kind !== 'transfer'),
    transfer: rows.filter((r) => r.kind === 'transfer'),
  }
}
