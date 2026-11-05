import { describe, expect, it } from 'vitest'
import {
  INVEST_REQUEST_PAYMENT_TYPES,
  REQUEST_PAYMENT_TYPES,
  fundingCurrenciesFromHint,
  fundingWalletLabel,
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

describe('multi-currency invest cash hint', () => {
  const hint = {
    wallet_id: 1,
    wallet_label: 'Инвест касса (UZS)',
    currency: 'UZS',
    wallets: [
      { wallet_id: 1, wallet_label: 'Инвест касса (UZS)', currency: 'UZS' },
      { wallet_id: 2, wallet_label: 'Инвест касса (USD)', currency: 'USD' },
    ],
  }

  it('offers currencies of all invest cash wallets, primary first, without locking', () => {
    expect(fundingCurrenciesFromHint(hint)).toEqual(['UZS', 'USD'])
    expect(lockedCurrencyFromHint(hint)).toBeNull()
  })

  it('locks currency when there is a single invest cash wallet', () => {
    expect(lockedCurrencyFromHint({ ...hint, wallets: [hint.wallets[0]] })).toBe('UZS')
    expect(fundingCurrenciesFromHint({ currency: null })).toBeNull()
  })

  it('labels the wallet of the selected currency', () => {
    expect(fundingWalletLabel(hint, 'USD')).toBe('Инвест касса (USD)')
    expect(fundingWalletLabel(hint, 'EUR')).toBe('Инвест касса (UZS)')
    expect(fundingWalletLabel(null, 'USD')).toBeNull()
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
