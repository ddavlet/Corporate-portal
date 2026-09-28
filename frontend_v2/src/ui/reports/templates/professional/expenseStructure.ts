import type { StatementResponse } from '../../../../lib/reportsApi'
import { PALETTE, rowValue } from './reportVisuals'

export type ExpenseSlice = { key: string; label: string; value: number; share: number; color: string; rowId: string }

/** Lines of an expense group for the ring: the largest `limit`, then «Остальное» (opens the whole group). */
export function expenseSlices(statement: StatementResponse, groupId: string, columnKey: string, limit = 6): ExpenseSlice[] {
  const group = statement.rows.find((row) => row.id === groupId)
  if (!group) return []
  const lines = statement.rows
    .filter((row) => row.parent === groupId)
    .map((row) => ({ row, value: rowValue(statement, row.id, columnKey) ?? 0 }))
    .filter((line) => line.value > 0)
    .sort((a, b) => b.value - a.value)
  if (lines.length === 0) {
    const value = rowValue(statement, groupId, columnKey) ?? 0
    return value > 0 ? [{ key: groupId, label: group.label, value, share: 1, color: PALETTE[0], rowId: groupId }] : []
  }
  const total = lines.reduce((sum, line) => sum + line.value, 0)
  const slices: ExpenseSlice[] = lines.slice(0, limit).map((line, index) => ({
    key: line.row.id,
    label: line.row.label,
    value: line.value,
    share: line.value / total,
    color: PALETTE[index % (PALETTE.length - 1)],
    rowId: line.row.id,
  }))
  const rest = lines.slice(limit).reduce((sum, line) => sum + line.value, 0)
  if (rest > 0) {
    slices.push({
      key: `${groupId}:rest`,
      label: 'Остальное',
      value: rest,
      share: rest / total,
      color: PALETTE[PALETTE.length - 1],
      rowId: groupId,
    })
  }
  return slices
}
