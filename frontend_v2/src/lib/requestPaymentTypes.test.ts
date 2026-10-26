import { describe, expect, it } from 'vitest'
import {
  INVEST_REQUEST_PAYMENT_TYPES,
  REQUEST_PAYMENT_TYPES,
  isInvestPaymentType,
  requestPaymentTypeSelectOptions,
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
