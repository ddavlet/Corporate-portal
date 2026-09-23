import { describe, expect, it } from 'vitest'
import { cellInsight } from './cellInsight'
import { STATEMENT } from './testStatement'

const plain = (text: string) => text.replace(/[  ]/g, ' ')
const row = (id: string) => STATEMENT.rows.find((candidate) => candidate.id === id)!
const column = (key: string) => STATEMENT.columns.find((candidate) => candidate.key === key)!
const describeLines = (rowId: string, columnKey: string) =>
  cellInsight(STATEMENT, row(rowId), column(columnKey)).map(
    (line) => `${line.label}: ${plain(line.text)}${line.tone ? ` (${line.tone})` : ''}`,
  )

describe('cellInsight', () => {
  it('compares a month with the previous month and shows the share of revenue for expenses', () => {
    expect(describeLines('opex.11111111', '2026-09')).toEqual([
      'Точно: 100 000 сум',
      'к Авг: −66,7% (good)',
      'Доля выручки: 14,3%',
    ])
  })

  it('uses the delta column for the period total', () => {
    expect(describeLines('rev', 'total')).toEqual(['Точно: 2 500 000 сум', 'к прошлому году: +212,5% (good)'])
  })

  it('has nothing to add for margins', () => {
    expect(describeLines('ebit_margin', 'total')).toEqual([])
  })

  it('does not compare the previous month or last year with a later column', () => {
    const monthPack = {
      ...STATEMENT,
      columns: [
        { ...column('2026-08'), label: 'Август 2026' },
        { ...column('2026-08'), key: '2026-07', label: 'Июль 2026', from: '2026-07-01', to: '2026-07-31' },
        { ...column('2026-08'), key: '2025-08', label: 'Август 2025', from: '2025-08-01', to: '2025-08-31' },
      ],
    }
    const marketing = { ...row('opex.11111111'), values: { '2026-08': '300000.00', '2026-07': '100000.00', '2025-08': '50000.00' } }
    for (const key of ['2026-07', '2025-08']) {
      const target = monthPack.columns.find((candidate) => candidate.key === key)!
      expect(cellInsight(monthPack, marketing, target).map((line) => line.label)).toEqual(['Точно'])
    }
  })
})
