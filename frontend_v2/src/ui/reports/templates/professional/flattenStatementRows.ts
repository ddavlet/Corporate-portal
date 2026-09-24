import type { StatementRow } from '../../../../lib/reportsApi'

export type DisplayVariant =
  | 'header'
  | 'item'
  | 'total'
  | 'collapsed'
  | 'nested'
  | 'result'
  | 'ratio'
  | 'balance'
  | 'spacer'

export type DisplayRow = {
  key: string
  variant: DisplayVariant
  row: StatementRow | null
  depth: number
  expanded: boolean
}

export function defaultOpenGroups(rows: StatementRow[]): string[] {
  return rows.filter((row) => row.kind === 'group' && row.depth === 0).map((row) => row.id)
}

/** Statement rows + open groups → table rows: open sections get a header and an «Итого» row. */
export function flattenStatementRows(rows: StatementRow[], open: ReadonlySet<string>): DisplayRow[] {
  const children = new Map<string, StatementRow[]>()
  for (const row of rows) {
    if (row.parent === null) continue
    const list = children.get(row.parent) ?? []
    list.push(row)
    children.set(row.parent, list)
  }
  const out: DisplayRow[] = []
  const walk = (row: StatementRow): void => {
    const expanded = open.has(row.id)
    if (row.kind === 'group' && row.depth === 0) {
      if (!expanded) {
        out.push({ key: row.id, variant: 'collapsed', row, depth: 0, expanded: false })
        return
      }
      out.push({ key: `${row.id}:header`, variant: 'header', row, depth: 0, expanded: true })
      for (const child of children.get(row.id) ?? []) walk(child)
      out.push({ key: `${row.id}:total`, variant: 'total', row, depth: 0, expanded: true })
      return
    }
    if (row.kind === 'group') {
      out.push({ key: row.id, variant: 'nested', row, depth: row.depth, expanded })
      if (expanded) for (const child of children.get(row.id) ?? []) walk(child)
      return
    }
    out.push({ key: row.id, variant: row.kind === 'line' ? 'item' : row.kind, row, depth: row.depth, expanded: false })
  }
  for (const row of rows) {
    if (row.parent !== null) continue
    if (row.separator_before) out.push({ key: `${row.id}:spacer`, variant: 'spacer', row: null, depth: 0, expanded: false })
    walk(row)
  }
  return out
}
