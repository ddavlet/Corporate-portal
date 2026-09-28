import { describe, expect, it } from 'vitest'
import type { StatementResponse, StatementRow } from '../../../../lib/reportsApi'
import { cashflowNarrative, initialsOf, pluralRu, pnlNarrative, REPORT_VISUALS, rowValue } from './reportVisuals'
import { STATEMENT } from './testStatement'

const text = (parts: { text: string }[]) => parts.map((part) => part.text).join('').replace(/[\u00a0\u202f]/g, ' ')

const row = (id: string, parent: string | null, value: string | null, over: Partial<StatementRow> = {}): StatementRow => ({
  id,
  parent,
  kind: parent ? 'line' : 'group',
  label: id,
  polarity: 'expense',
  depth: parent ? 1 : 0,
  drillable: true,
  strong: false,
  hint: '',
  separator_before: false,
  values: { total: value },
  deltas: {},
  ...over,
})

describe('REPORT_VISUALS', () => {
  it('names the headline number and the expense group of each report', () => {
    expect([REPORT_VISUALS.pnl.heroKpi, REPORT_VISUALS.pnl.structureRow]).toEqual(['net', 'opex'])
    expect([REPORT_VISUALS.cashflow.heroKpi, REPORT_VISUALS.cashflow.structureRow]).toEqual(['close', 'out_op'])
  })
})

describe('rowValue', () => {
  it('reads a number and treats missing values as no data', () => {
    expect(rowValue(STATEMENT, 'rev', 'total')).toBe(2500000)
    expect(rowValue(STATEMENT, 'rev', 'nope')).toBeNull()
    expect(rowValue(STATEMENT, 'ghost', 'total')).toBeNull()
  })
})

describe('pnlNarrative', () => {
  it('states revenue, expenses with their share and the largest expense', () => {
    expect(text(pnlNarrative(STATEMENT, 'total', 'm'))).toBe(
      'Выручка 2,5 млн, операционные расходы 0,4 млн (16,0% выручки). Больше всего потрачено на маркетинг: 0,4 млн.',
    )
    expect(pnlNarrative(STATEMENT, 'total', 'm').filter((part) => part.strong)).toHaveLength(3)
  })

  it('leaves out the share when there is no revenue', () => {
    const statement: StatementResponse = {
      ...STATEMENT,
      rows: [row('rev', null, null, { polarity: 'income' }), row('opex', null, '100000.00')],
    }
    expect(text(pnlNarrative(statement, 'total', 'k'))).toBe('Выручка —, операционные расходы 100 тыс..')
  })
})

describe('cashflowNarrative', () => {
  it('states money in, money out and the closing balance', () => {
    const statement: StatementResponse = {
      ...STATEMENT,
      report: 'cashflow',
      rows: [
        row('open', null, '1000000.00', { kind: 'balance', polarity: 'result' }),
        row('in', null, '3000000.00', { polarity: 'income' }),
        row('out_op', null, '1200000.00'),
        row('out_other', null, '300000.00'),
        row('out_inv', null, null),
        row('close', null, '2500000.00', { kind: 'balance', polarity: 'result', strong: true }),
      ],
    }
    expect(text(cashflowNarrative(statement, 'total', 'm'))).toBe(
      'Поступило 3,0 млн, выплачено 1,5 млн. Остаток на конец периода 2,5 млн.',
    )
  })
})

describe('initialsOf', () => {
  it('uses the name, not the legal form or quotes', () => {
    expect(initialsOf('ООО «Silk Road Logistics»')).toBe('SR')
    expect(initialsOf('Азиз Рахимов')).toBe('АР')
    expect(initialsOf('  ')).toBe('?')
  })
})

describe('pluralRu', () => {
  it('picks the Russian form for the number', () => {
    expect([1, 2, 5, 11, 21, 22, 25].map((n) => pluralRu(n, 'заявка', 'заявки', 'заявок'))).toEqual([
      'заявка',
      'заявки',
      'заявок',
      'заявок',
      'заявка',
      'заявки',
      'заявок',
    ])
  })
})
