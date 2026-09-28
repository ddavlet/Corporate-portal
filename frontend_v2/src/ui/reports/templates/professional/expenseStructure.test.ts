import { describe, expect, it } from 'vitest'
import type { StatementResponse, StatementRow } from '../../../../lib/reportsApi'
import { expenseSlices } from './expenseStructure'
import { STATEMENT } from './testStatement'

const OPEX = STATEMENT.rows.find((row) => row.id === 'opex') as StatementRow

const line = (id: string, value: string | null): StatementRow => ({
  id: `opex.${id}`,
  parent: 'opex',
  kind: 'line',
  label: `Статья ${id}`,
  polarity: 'expense',
  depth: 1,
  drillable: true,
  strong: false,
  hint: '',
  separator_before: false,
  values: { total: value },
  deltas: {},
})

function withLines(values: (string | null)[]): StatementResponse {
  const group = { ...OPEX, values: { total: '999' } }
  return { ...STATEMENT, rows: [group, ...values.map((value, index) => line(String.fromCharCode(97 + index), value))] }
}

describe('expenseSlices', () => {
  it('keeps the six largest lines and folds the rest into «Остальное»', () => {
    const slices = expenseSlices(withLines(['800', '700', '600', '500', '400', '300', '200', '100']), 'opex', 'total')
    expect(slices.map((slice) => slice.label)).toEqual([
      'Статья a',
      'Статья b',
      'Статья c',
      'Статья d',
      'Статья e',
      'Статья f',
      'Остальное',
    ])
    expect(slices.at(-1)).toMatchObject({ value: 300, rowId: 'opex' })
    expect(slices[0].share).toBeCloseTo(800 / 3600)
  })

  it('skips lines without money', () => {
    const slices = expenseSlices(withLines(['500', null, '0', '-20']), 'opex', 'total')
    expect(slices.map((slice) => slice.rowId)).toEqual(['opex.a'])
  })

  it('shows the group itself when it has no lines', () => {
    const statement = { ...STATEMENT, rows: [{ ...OPEX, values: { total: '400' } }] }
    expect(expenseSlices(statement, 'opex', 'total')).toEqual([expect.objectContaining({ rowId: 'opex', value: 400, share: 1 })])
  })
})
