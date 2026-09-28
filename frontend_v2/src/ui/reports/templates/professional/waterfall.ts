import type { StatementResponse, StatementRow } from '../../../../lib/reportsApi'
import { rowValue } from './reportVisuals'

export type WaterfallStep = {
  key: string
  label: string
  kind: 'start' | 'up' | 'down' | 'total'
  value: number
  from: number
  to: number
  /** The row a click opens; null for results and for the opening balance. */
  rowId: string | null
}

const EPSILON = 0.005

/**
 * Bars from the statement rows: income groups go up, expense groups go down line by line (the largest
 * `maxLines`, then «Прочее»), a result or balance is a total bar only when it equals the running sum.
 * The walk ends at the first strong row (net profit, closing balance).
 */
export function buildWaterfall(statement: StatementResponse, columnKey: string, maxLines = 4): WaterfallStep[] {
  const value = (row: StatementRow) => rowValue(statement, row.id, columnKey) ?? 0
  const steps: WaterfallStep[] = []
  let running = 0
  let started = false
  const move = (key: string, label: string, amount: number, kind: 'up' | 'down', rowId: string | null) => {
    if (amount === 0) return
    const to = kind === 'up' ? running + amount : running - amount
    steps.push({ key, label, kind, value: amount, from: running, to, rowId })
    running = to
  }
  for (const row of statement.rows.filter((candidate) => candidate.parent === null)) {
    if (row.kind === 'ratio') continue
    const amount = value(row)
    if (row.kind === 'balance' && !started) {
      steps.push({ key: row.id, label: row.label, kind: 'start', value: amount, from: 0, to: amount, rowId: null })
      running = amount
      started = true
    } else if (row.kind === 'group' || row.kind === 'line') {
      started = true
      if (row.polarity === 'income') {
        move(row.id, row.label, amount, 'up', row.drillable ? row.id : null)
      } else {
        const lines = statement.rows
          .filter((child) => child.parent === row.id)
          .map((child) => ({ child, amount: value(child) }))
          .filter((line) => line.amount !== 0)
          .sort((a, b) => b.amount - a.amount)
        if (row.polarity !== 'expense' || lines.length === 0) {
          move(row.id, row.label, amount, 'down', row.drillable ? row.id : null)
        } else {
          for (const line of lines.slice(0, maxLines)) {
            move(line.child.id, line.child.label, line.amount, 'down', line.child.drillable ? line.child.id : null)
          }
          const rest = lines.slice(maxLines).reduce((sum, line) => sum + line.amount, 0)
          move(`${row.id}:rest`, 'Прочее', rest, 'down', row.drillable ? row.id : null)
        }
      }
    } else if (row.kind === 'result' || row.kind === 'balance') {
      if (Math.abs(amount - running) < EPSILON) {
        steps.push({ key: row.id, label: row.label, kind: 'total', value: amount, from: 0, to: amount, rowId: null })
      }
    }
    if (row.strong) break
  }
  return steps
}

/**
 * A bar label in lines of about `maxChars`, broken between words; a single long word keeps its line.
 * Only a name that does not fit in `maxLines` ends with «…».
 */
export function wrapLabel(label: string, maxChars: number, maxLines = 3): string[] {
  const lines: string[] = []
  for (const word of label.split(/\s+/).filter(Boolean)) {
    const last = lines[lines.length - 1]
    if (last !== undefined && `${last} ${word}`.length <= maxChars) lines[lines.length - 1] = `${last} ${word}`
    else lines.push(word)
  }
  if (lines.length <= maxLines) return lines
  const shown = lines.slice(0, maxLines)
  shown[maxLines - 1] = `${shown[maxLines - 1]}…`
  return shown
}
