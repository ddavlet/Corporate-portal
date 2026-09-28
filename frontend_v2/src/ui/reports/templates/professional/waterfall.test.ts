import { describe, expect, it } from 'vitest'
import type { StatementResponse, StatementRow } from '../../../../lib/reportsApi'
import { STATEMENT } from './testStatement'
import { buildWaterfall, wrapLabel } from './waterfall'

const row = (id: string, over: Partial<StatementRow>): StatementRow => ({
  id,
  parent: null,
  kind: 'group',
  label: id,
  polarity: 'expense',
  depth: 0,
  drillable: true,
  strong: false,
  hint: '',
  separator_before: false,
  values: {},
  deltas: {},
  ...over,
})
const v = (value: string | null) => ({ values: { total: value } })

function pnl(rows: StatementRow[]): StatementResponse {
  return { ...STATEMENT, rows }
}

const PNL_ROWS: StatementRow[] = [
  row('rev', { polarity: 'income', label: 'Выручка', ...v('1000') }),
  row('opex', { label: 'Операционные расходы', ...v('600') }),
  ...['a', 'b', 'c', 'd', 'e', 'f'].map((id, i) =>
    row(`opex.${id}`, { parent: 'opex', kind: 'line', label: `Статья ${id}`, ...v(String(150 - i * 20)) }),
  ),
  row('ebit', { kind: 'result', polarity: 'result', label: 'EBIT', drillable: false, ...v('400') }),
  row('ebit_margin', { kind: 'ratio', polarity: 'result', drillable: false, ...v('0.4') }),
  row('other', { label: 'Прочие расходы', ...v('50') }),
  row('net', { kind: 'result', polarity: 'result', label: 'Чистая прибыль', drillable: false, strong: true, ...v('350') }),
  row('inv', { kind: 'line', polarity: 'neutral', label: 'Выплаты инвесторам', ...v('100') }),
]

describe('buildWaterfall', () => {
  it('walks from revenue through expense lines to net profit', () => {
    const steps = buildWaterfall(pnl(PNL_ROWS), 'total')
    expect(steps.map((s) => `${s.kind}:${s.label}:${s.value}`)).toEqual([
      'up:Выручка:1000',
      'down:Статья a:150',
      'down:Статья b:130',
      'down:Статья c:110',
      'down:Статья d:90',
      'down:Прочее:120',
      'total:EBIT:400',
      'down:Прочие расходы:50',
      'total:Чистая прибыль:350',
    ])
    expect(steps[5].rowId).toBe('opex')
    expect(steps[1]).toMatchObject({ from: 1000, to: 850, rowId: 'opex.a' })
    expect(steps.at(-1)).toMatchObject({ from: 0, to: 350, rowId: null })
  })

  it('starts a cashflow at the opening balance and skips a result that is not the running total', () => {
    const rows = [
      row('open', { kind: 'balance', polarity: 'result', label: 'Остаток на начало', drillable: false, ...v('500') }),
      row('in', { polarity: 'income', label: 'Поступления', ...v('300') }),
      row('out_op', { label: 'Операционные выплаты', ...v('200') }),
      row('flow', { kind: 'result', polarity: 'result', label: 'Чистый денежный поток', drillable: false, ...v('100') }),
      row('close', { kind: 'balance', polarity: 'result', label: 'Остаток на конец', drillable: false, strong: true, ...v('600') }),
    ]
    const steps = buildWaterfall({ ...STATEMENT, report: 'cashflow', rows }, 'total')
    expect(steps.map((s) => `${s.kind}:${s.label}`)).toEqual([
      'start:Остаток на начало',
      'up:Поступления',
      'down:Операционные выплаты',
      'total:Остаток на конец',
    ])
  })

  it('draws a loss below zero', () => {
    const rows = [
      row('rev', { polarity: 'income', label: 'Выручка', ...v('100') }),
      row('opex', { label: 'Операционные расходы', ...v('250') }),
      row('ebit', { kind: 'result', polarity: 'result', label: 'EBIT', drillable: false, strong: true, ...v('-150') }),
    ]
    const steps = buildWaterfall(pnl(rows), 'total')
    expect(steps.at(-1)).toMatchObject({ kind: 'total', from: 0, to: -150 })
  })

  it('treats missing values as nothing', () => {
    const rows = [
      row('rev', { polarity: 'income', label: 'Выручка', ...v(null) }),
      row('opex', { label: 'Операционные расходы', ...v(null) }),
      row('ebit', { kind: 'result', polarity: 'result', label: 'EBIT', drillable: false, strong: true, ...v(null) }),
    ]
    expect(buildWaterfall(pnl(rows), 'total').map((s) => s.kind)).toEqual(['total'])
  })
})

describe('wrapLabel', () => {
  it('breaks a long name between words instead of cutting it', () => {
    expect(wrapLabel('Операционные выплаты', 11)).toEqual(['Операционные', 'выплаты'])
    expect(wrapLabel('Прочие поступления от клиентов', 11)).toEqual(['Прочие', 'поступления', 'от клиентов'])
    expect(wrapLabel('EBIT', 11)).toEqual(['EBIT'])
  })

  it('ends with an ellipsis only when even three lines are not enough', () => {
    expect(wrapLabel('Расходы на обслуживание и ремонт складского оборудования', 11)).toEqual(['Расходы на', 'обслуживание', 'и ремонт…'])
  })
})
