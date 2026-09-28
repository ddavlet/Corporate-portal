import type { ReportKind, StatementResponse } from '../../../../lib/reportsApi'
import { formatAmount, UNITS_SHORT, type Units } from '../../../../lib/reportsFormat'

export type StoryPart = { text: string; strong?: boolean }

export type ReportVisuals = {
  /** KPI shown large in the summary card. */
  heroKpi: string
  /** Ratio row drawn as the margin bar; null when the report has none. */
  marginRow: string | null
  /** Expense group whose lines make up the ring chart. */
  structureRow: string
  narrative: (statement: StatementResponse, columnKey: string, units: Units) => StoryPart[]
}

/** Chart colours; the last one is kept for «Остальное» / «Прочее». */
export const PALETTE = ['#1f6feb', '#14a39a', '#e59a1a', '#8b5cf6', '#e8664f', '#64748b', '#aab4c3'] as const

export function rowValue(statement: StatementResponse, rowId: string, columnKey: string): number | null {
  const raw = statement.rows.find((row) => row.id === rowId)?.values[columnKey]
  if (raw === null || raw === undefined || raw === '') return null
  const value = Number(raw)
  return Number.isFinite(value) ? value : null
}

/** An amount with its unit, or a bare «—» when there is nothing to show. */
function money(value: number | null, units: Units): string {
  const text = formatAmount(value === null ? null : String(value), units)
  return text === '—' ? text : `${text} ${UNITS_SHORT[units]}`
}

const lowerFirst = (text: string) => text.charAt(0).toLowerCase() + text.slice(1)

export function pnlNarrative(statement: StatementResponse, columnKey: string, units: Units): StoryPart[] {
  const revenue = rowValue(statement, 'rev', columnKey)
  const expenses = rowValue(statement, 'opex', columnKey)
  const parts: StoryPart[] = [
    { text: 'Выручка ' },
    { text: money(revenue, units), strong: true },
    { text: ', операционные расходы ' },
    { text: money(expenses, units), strong: true },
  ]
  if (revenue && revenue > 0 && expenses !== null) {
    const share = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format((expenses / revenue) * 100)
    parts.push({ text: ` (${share}% выручки)` })
  }
  parts.push({ text: '.' })
  const largest = statement.rows
    .filter((row) => row.parent === 'opex')
    .map((row) => ({ row, value: rowValue(statement, row.id, columnKey) ?? 0 }))
    .filter((line) => line.value > 0)
    .sort((a, b) => b.value - a.value)[0]
  if (largest) {
    parts.push({ text: ` Больше всего потрачено на ${lowerFirst(largest.row.label)}: ` })
    parts.push({ text: money(largest.value, units), strong: true })
    parts.push({ text: '.' })
  }
  return parts
}

export function cashflowNarrative(statement: StatementResponse, columnKey: string, units: Units): StoryPart[] {
  const paidOut = ['out_op', 'out_other', 'out_inv']
    .map((id) => rowValue(statement, id, columnKey))
    .reduce<number>((sum, value) => sum + (value ?? 0), 0)
  return [
    { text: 'Поступило ' },
    { text: money(rowValue(statement, 'in', columnKey), units), strong: true },
    { text: ', выплачено ' },
    { text: money(paidOut, units), strong: true },
    { text: '. Остаток на конец периода ' },
    { text: money(rowValue(statement, 'close', columnKey), units), strong: true },
    { text: '.' },
  ]
}

export const REPORT_VISUALS: Record<ReportKind, ReportVisuals> = {
  pnl: { heroKpi: 'net', marginRow: 'net_margin', structureRow: 'opex', narrative: pnlNarrative },
  cashflow: { heroKpi: 'close', marginRow: null, structureRow: 'out_op', narrative: cashflowNarrative },
}

const LEGAL_FORMS = new Set(['ООО', 'ИП', 'ЧП', 'АО', 'ОАО', 'ЗАО', 'OOO', 'LLC', 'MCHJ', 'XK'])

/** Two letters for an avatar: the name's first words, without the legal form and quotes. */
export function initialsOf(name: string): string {
  const words = name
    .replace(/[«»"'“”]/g, ' ')
    .split(/\s+/)
    .filter((word) => word && !LEGAL_FORMS.has(word.toUpperCase()))
  const letters = words
    .slice(0, 2)
    .map((word) => word.charAt(0).toUpperCase())
    .join('')
  return letters || '?'
}

export function pluralRu(count: number, one: string, few: string, many: string): string {
  const tens = count % 100
  const units = count % 10
  if (units === 1 && tens !== 11) return one
  if (units >= 2 && units <= 4 && (tens < 12 || tens > 14)) return few
  return many
}
