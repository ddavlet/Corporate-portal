import { describe, expect, it } from 'vitest'
import type { StructuredReportRow } from '../../../../lib/api'
import { filterForMatrixRow, operationRowKey, operationsFilterCaption, rowMatchesSection } from './reportsOperationsFilter'

const row = (over: Partial<StructuredReportRow>): StructuredReportRow => ({
  id: '1',
  date: '2026-08-01',
  amount: '10',
  direction: 'expense',
  purpose: '',
  description: '',
  channel: 'OTHER',
  raw: {},
  ...over,
})

describe('filterForMatrixRow', () => {
  it('limits the operating-expense total to the operational section', () => {
    expect(
      filterForMatrixRow({ key: 'sum:operational-expense', kind: 'summary', label: 'Итого операционные расходы' }),
    ).toEqual({
      direction: 'expense',
      category: null,
      section: 'operational',
    })
  })

  it('keeps same-named categories of operational and other expenses apart', () => {
    expect(filterForMatrixRow({ key: 'exp:op:Налоги', kind: 'expense', label: 'Налоги' })).toEqual({
      direction: 'expense',
      category: 'Налоги',
      section: 'operational',
    })
    expect(filterForMatrixRow({ key: 'exp:other:Налоги', kind: 'expense', label: 'Налоги' })?.section).toBe('other')
  })

  it('lists investor payouts by section', () => {
    expect(filterForMatrixRow({ key: 'sum:invest_returns', kind: 'summary', label: 'Выплаты по инвестициям' })).toEqual({
      direction: null,
      category: null,
      section: 'invest_returns',
    })
  })

  it('maps section header rows', () => {
    expect(filterForMatrixRow({ key: 'section:other-expense', kind: 'section', label: 'Прочие расходы' })?.section).toBe(
      'other',
    )
  })

  it('returns null for computed rows', () => {
    expect(filterForMatrixRow({ key: 'sum:ebit', kind: 'summary', label: 'EBIT' })).toBeNull()
  })
})

describe('rowMatchesSection', () => {
  it('drops other-expense rows from an operational filter', () => {
    expect(rowMatchesSection(row({ section: 'other' }), 'operational')).toBe(false)
  })

  it('keeps rows from backends that do not send a section', () => {
    expect(rowMatchesSection(row({}), 'operational')).toBe(true)
  })

  it('keeps everything when no section is selected', () => {
    expect(rowMatchesSection(row({ section: 'other' }), null)).toBe(true)
  })
})

describe('operationRowKey', () => {
  it('includes section and source so a bank and a cash receipt never collide', () => {
    const bank = row({ direction: 'revenue', section: 'revenue', raw: { source: 'bank' } })
    const cash = row({ direction: 'revenue', section: 'revenue', raw: { source: 'cash' } })
    expect(operationRowKey(bank, 0)).toBe('revenue:bank:1:2026-08-01:0')
    expect(operationRowKey(cash, 0)).toBe('revenue:cash:1:2026-08-01:0')
  })
})

describe('operationsFilterCaption', () => {
  it('names the section once and never says «Все» next to a section', () => {
    expect(operationsFilterCaption({ direction: 'revenue', section: 'revenue', category: null, month: null })).toBe('Доходы')
    expect(operationsFilterCaption({ direction: null, section: 'invest_returns', category: null, month: null })).toBe(
      'Выплаты по инвестициям',
    )
    expect(
      operationsFilterCaption({ direction: 'expense', section: 'operational', category: 'Аренда', month: 'Август 2026' }),
    ).toBe('Операционные расходы / Аренда / Август 2026')
    expect(operationsFilterCaption({ direction: 'expense', section: null, category: null, month: null })).toBe('Расход')
    expect(operationsFilterCaption({ direction: null, section: null, category: null, month: 'Август 2026' })).toBe(
      'Все операции / Август 2026',
    )
  })
})
