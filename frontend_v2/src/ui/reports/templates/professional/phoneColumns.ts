import type { StatementColumn } from '../../../../lib/reportsApi'

/** Period columns a phone user can pick from (chips). */
export function phonePeriodColumns(columns: StatementColumn[]): StatementColumn[] {
  return columns.filter((column) => column.kind === 'period')
}

/** Chips for the period columns; a label that repeats (quarters across two years) gets its dates. */
export function phoneChipOptions(columns: StatementColumn[]): { value: string; label: string }[] {
  const periods = phonePeriodColumns(columns)
  const counts = new Map<string, number>()
  for (const column of periods) counts.set(column.label, (counts.get(column.label) ?? 0) + 1)
  return periods.map((column) => ({
    value: column.key,
    label: (counts.get(column.label) ?? 0) > 1 && column.sublabel ? `${column.label} ${column.sublabel}` : column.label,
  }))
}

/** The chosen period if it is one, otherwise the latest: the reporting month, or the last month or quarter. */
export function resolvePhoneColumnKey(columns: StatementColumn[], selected: string | null): string | null {
  const periods = phonePeriodColumns(columns)
  if (selected && periods.some((column) => column.key === selected)) return selected
  let latest: StatementColumn | null = null
  for (const column of periods) {
    if (!latest || (column.to ?? '') > (latest.to ?? '')) latest = column
  }
  return latest?.key ?? null
}

/** On a phone the table shows one period plus the totals; comparisons and deltas stay on wider screens. */
export function phoneColumnKeys(columns: StatementColumn[], selected: string | null): Set<string> {
  const keys = new Set(columns.filter((column) => column.kind === 'total').map((column) => column.key))
  const period = resolvePhoneColumnKey(columns, selected)
  if (period) keys.add(period)
  return keys
}
