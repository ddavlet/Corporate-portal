import type { StructuredReportRow } from '../../../../lib/api'

export type ReportSection = NonNullable<StructuredReportRow['section']>

export type OperationsFilter = {
  direction: 'revenue' | 'expense' | null
  category: string | null
  section: ReportSection | null
}

export const SECTION_LABELS: Record<ReportSection, string> = {
  revenue: 'Доходы',
  operational: 'Операционные расходы',
  other: 'Прочие расходы',
  invest_returns: 'Выплаты по инвестициям',
}

export type OperationsCaptionParts = {
  direction: 'revenue' | 'expense' | null
  section: ReportSection | null
  category: string | null
  month: string | null
}

/** «Операционные расходы / Аренда / Август 2026»: the section names itself, so it is never paired with «Все» or «Доход». */
export function operationsFilterCaption(parts: OperationsCaptionParts): string {
  const head = parts.section
    ? SECTION_LABELS[parts.section]
    : parts.direction === 'revenue'
      ? 'Доход'
      : parts.direction === 'expense'
        ? 'Расход'
        : 'Все операции'
  return [head, parts.category, parts.month].filter(Boolean).join(' / ')
}

type MatrixRowRef = { key: string; kind: 'section' | 'revenue' | 'expense' | 'summary'; label: string }

/** Which operations a click on a matrix row or cell lists; null for computed rows (EBIT, net profit, balances). */
export function filterForMatrixRow(row: MatrixRowRef): OperationsFilter | null {
  if (row.kind === 'revenue') return { direction: 'revenue', category: row.label, section: 'revenue' }
  if (row.kind === 'expense') {
    return {
      direction: 'expense',
      category: row.label,
      section: row.key.startsWith('exp:other:') ? 'other' : 'operational',
    }
  }
  switch (row.key) {
    case 'section:income':
    case 'sum:income':
      return { direction: 'revenue', category: null, section: 'revenue' }
    case 'section:operational-expense':
    case 'sum:operational-expense':
      return { direction: 'expense', category: null, section: 'operational' }
    case 'section:other-expense':
    case 'sum:other-expense':
      return { direction: 'expense', category: null, section: 'other' }
    case 'sum:invest_returns':
      return { direction: null, category: null, section: 'invest_returns' }
    default:
      return null
  }
}

/** Rows from backends that do not send `section` are never hidden by a section filter. */
export function rowMatchesSection(row: Pick<StructuredReportRow, 'section'>, section: ReportSection | null): boolean {
  if (!section || !row.section) return true
  return row.section === section
}

/** Bank and cash receipts can share an id and a date, so the key adds section, source and position. */
export function operationRowKey(row: StructuredReportRow, index: number): string {
  const source = typeof row.raw?.source === 'string' ? row.raw.source : ''
  return `${row.section ?? row.direction}:${source}:${row.id}:${row.date ?? ''}:${index}`
}
