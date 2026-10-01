import { describe, expect, it } from 'vitest'
import { buildRulesFromForm, defaultInvestBuckets, formFromRules, movePurposes, splitList } from './reportRulesModel'

const RULES = {
  start_month: '2026-02',
  opening_balance: '250',
  cash_exclude_operations: ['Возврат'],
  bank_exclude_purposes: ['уставного'],
  request_exclude_categories: [],
  request_payment_types_for_pnl: ['Перечисление'],
  payment_purpose_operational: ['Аренда'],
  payment_purpose_other: ['Налоги'],
  payment_purpose_invest_returns: [],
  invest_return_type_operational: ['проценты', 'доля_прибыли'],
  invest_return_type_other: ['тело_инвестиций'],
  invest_return_type_invest_returns: ['дивиденды'],
}

describe('report rules form model', () => {
  it('turns saved rules into the form and back', () => {
    expect(buildRulesFromForm(formFromRules(RULES), { bankExclusions: true })).toEqual(RULES)
  })

  it('sends bank exclusions only for a report that applies them', () => {
    const rules = buildRulesFromForm(formFromRules(RULES), { bankExclusions: false })
    expect(rules).not.toHaveProperty('bank_exclude_purposes')
    expect(rules.start_month).toBe('2026-02')
  })

  it('starts empty rules with a complete split of investor payouts and a zero opening balance', () => {
    const values = formFromRules({})
    expect(values.investBucketByType).toEqual(defaultInvestBuckets())
    expect(buildRulesFromForm(values, { bankExclusions: false }).opening_balance).toBe('0')
  })

  it('keeps a payment purpose in one section only', () => {
    const moved = movePurposes(formFromRules(RULES), 'purposeOther', ['Налоги', 'Аренда'])
    expect(moved.purposeOther).toEqual(['Налоги', 'Аренда'])
    expect(moved.purposeOperational).toEqual([])
  })

  it('splits typed lists by lines and commas and drops blanks', () => {
    expect(splitList(' Аренда \n\nНалоги, Связь ')).toEqual(['Аренда', 'Налоги', 'Связь'])
  })
})
