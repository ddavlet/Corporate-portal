import type { StatementColumn, StatementDelta, StatementResponse, StatementRow } from '../../../../lib/reportsApi'
import { formatDelta, formatExact, formatRatio, isFavorable } from '../../../../lib/reportsFormat'

export type InsightLine = { label: string; text: string; tone: 'good' | 'bad' | null }

function deltaLine(row: StatementRow, label: string, delta: StatementDelta | undefined): InsightLine | null {
  const view = formatDelta(delta ?? undefined)
  if (!view) return null
  const favorable = isFavorable(row.polarity, view.direction)
  return { label, text: view.text, tone: favorable === null ? null : favorable ? 'good' : 'bad' }
}

function dayBefore(iso: string): string {
  const [year, month, day] = iso.split('-').map(Number)
  return new Date(Date.UTC(year, month - 1, day - 1)).toISOString().slice(0, 10)
}

function pctChange(current: string | null | undefined, previous: string | null | undefined): string | null {
  if (current == null || previous == null) return null
  const a = Number(current)
  const b = Number(previous)
  if (!Number.isFinite(a) || !Number.isFinite(b) || b === 0) return null
  return String((a - b) / Math.abs(b))
}

/** Hover details for a money cell: exact amount, change against the previous period and last year, share of revenue for expenses. */
export function cellInsight(statement: StatementResponse, row: StatementRow, column: StatementColumn): InsightLine[] {
  const value = row.values[column.key] ?? null
  if (value === null || row.kind === 'ratio') return []
  const lines: InsightLine[] = [{ label: 'Точно', text: `${formatExact(value)} сум`, tone: null }]
  const deltaColumns = statement.columns.filter((candidate) => candidate.kind === 'delta' && candidate.delta_of?.[0] === column.key)
  for (const deltaColumn of deltaColumns) {
    const line = deltaLine(row, deltaColumn.sublabel || 'Δ', row.deltas[deltaColumn.key] ?? undefined)
    if (line) lines.push(line)
  }
  if (deltaColumns.length === 0 && column.kind === 'period') {
    const periods = statement.columns.filter((candidate) => candidate.kind === 'period')
    const left = periods[periods.findIndex((candidate) => candidate.key === column.key) - 1]
    // Only a column that ends the day before this one starts; the monthly report's neighbours are not consecutive.
    const previous = left?.to && column.from && left.to === dayBefore(column.from) ? left : undefined
    const pct = previous ? pctChange(value, row.values[previous.key]) : null
    const line = previous && pct !== null ? deltaLine(row, `к ${previous.label.replace('*', '')}`, { pct }) : null
    if (line) lines.push(line)
  }
  if (row.polarity === 'expense') {
    const income = statement.rows.find((candidate) => candidate.parent === null && candidate.polarity === 'income')
    const base = income?.values[column.key]
    if (base && Number(base) > 0) {
      lines.push({
        label: statement.report === 'pnl' ? 'Доля выручки' : 'Доля поступлений',
        text: formatRatio(String(Number(value) / Number(base))),
        tone: null,
      })
    }
  }
  return lines
}
