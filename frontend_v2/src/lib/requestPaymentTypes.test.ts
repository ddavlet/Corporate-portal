import { describe, expect, it } from 'vitest'
import {
  INVEST_REQUEST_PAYMENT_TYPES,
  REQUEST_PAYMENT_TYPES,
  isInvestPaymentType,
  lockedCurrencyFromHint,
  reportRulePaymentTypeOptions,
  requestPaymentTypeSelectOptions,
  vendorKindForPaymentType,
  withoutInvestTypesUnlessEnabled,
} from './requestPaymentTypes'

describe('requestPaymentTypes', () => {
  it('includes payroll accrual type', () => {
    expect(REQUEST_PAYMENT_TYPES).toContain('Начисление ЗП')
  })

  it('select options cover all payment types', () => {
    expect(requestPaymentTypeSelectOptions()).toHaveLength(REQUEST_PAYMENT_TYPES.length)
    expect(requestPaymentTypeSelectOptions().map((o) => o.value)).toEqual([...REQUEST_PAYMENT_TYPES])
  })

  it('contains both invest payment types', () => {
    expect(REQUEST_PAYMENT_TYPES).toContain('Инвест. наличные')
    expect(REQUEST_PAYMENT_TYPES).toContain('Инвест. перечисление')
    expect(INVEST_REQUEST_PAYMENT_TYPES).toHaveLength(2)
  })

  it('isInvestPaymentType distinguishes invest types', () => {
    expect(isInvestPaymentType('Инвест. наличные')).toBe(true)
    expect(isInvestPaymentType('Инвест. перечисление')).toBe(true)
    expect(isInvestPaymentType('Наличные')).toBe(false)
  })
})

describe('lockedCurrencyFromHint', () => {
  it('locks currency only when the hint carries one', () => {
    expect(lockedCurrencyFromHint({ currency: 'UZS' })).toBe('UZS')
    expect(lockedCurrencyFromHint({ currency: null })).toBeNull()
    expect(lockedCurrencyFromHint(null)).toBeNull()
  })
})

describe('vendorKindForPaymentType', () => {
  it('treats invest cash as cash and other types as transfer', () => {
    expect(vendorKindForPaymentType('Наличные')).toBe('cash')
    expect(vendorKindForPaymentType('Инвест. наличные')).toBe('cash')
    expect(vendorKindForPaymentType('Инвест. перечисление')).toBe('transfer')
    expect(vendorKindForPaymentType('Перечисление')).toBe('transfer')
    expect(vendorKindForPaymentType('Платежная карта')).toBe('transfer')
  })
})

describe('withoutInvestTypesUnlessEnabled', () => {
  const options = requestPaymentTypeSelectOptions()

  it('drops invest types when the funding mode is off', () => {
    const values = withoutInvestTypesUnlessEnabled(options, (o) => o.value, false).map((o) => o.value)
    expect(values).not.toContain('Инвест. наличные')
    expect(values).not.toContain('Инвест. перечисление')
    expect(values).toContain('Наличные')
  })

  it('keeps all types when the funding mode is on', () => {
    expect(withoutInvestTypesUnlessEnabled(options, (o) => o.value, true)).toHaveLength(options.length)
  })
})

describe('reportRulePaymentTypeOptions', () => {
  it('never offers invest types', () => {
    const values = reportRulePaymentTypeOptions([]).map((o) => o.value)
    expect(values.some(isInvestPaymentType)).toBe(false)
    expect(values).toContain('Перечисление')
  })

  it('keeps already saved invest types selectable', () => {
    const values = reportRulePaymentTypeOptions(['Перечисление', 'Инвест. перечисление']).map((o) => o.value)
    expect(values).toContain('Инвест. перечисление')
    expect(values).not.toContain('Инвест. наличные')
  })
})
