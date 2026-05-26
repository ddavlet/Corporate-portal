import { describe, expect, it } from 'vitest'
import { REQUEST_PAYMENT_TYPES, requestPaymentTypeSelectOptions } from './requestPaymentTypes'

describe('requestPaymentTypes', () => {
  it('includes payroll accrual type', () => {
    expect(REQUEST_PAYMENT_TYPES).toContain('Начисление ЗП')
  })

  it('select options cover all payment types', () => {
    expect(requestPaymentTypeSelectOptions()).toHaveLength(REQUEST_PAYMENT_TYPES.length)
    expect(requestPaymentTypeSelectOptions().map((o) => o.value)).toEqual([...REQUEST_PAYMENT_TYPES])
  })
})
