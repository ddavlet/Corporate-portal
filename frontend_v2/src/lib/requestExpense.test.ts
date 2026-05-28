import { describe, expect, it } from 'vitest'
import { canOpenLinkedExpense, linkedExpenseFrontendPath, linkedExpenseLabel } from './requestExpense'

describe('linkedExpenseFrontendPath', () => {
  it('returns portal paths for cash, bank, payroll', () => {
    expect(linkedExpenseFrontendPath({ module: 'cash', id: 12 })).toBe('/cash/expenses/12')
    expect(linkedExpenseFrontendPath({ module: 'bank', id: 34 })).toBe('/bank/expenses/34')
    expect(linkedExpenseFrontendPath({ module: 'payroll', id: 5 })).toBe('/payroll/5')
  })

  it('returns telegram paths for cash and bank', () => {
    expect(linkedExpenseFrontendPath({ module: 'cash', id: 1 }, { telegram: true })).toBe('/tg/cash/expenses/1')
    expect(linkedExpenseFrontendPath({ module: 'bank', id: 2 }, { telegram: true })).toBe('/tg/bank/expenses/2')
  })

  it('builds human-readable labels', () => {
    expect(linkedExpenseLabel({ module: 'cash', id: 12 })).toBe('Касса · #12')
    expect(linkedExpenseLabel({ module: 'payroll', id: 3, doc_id: 'ZP-01' })).toBe('Начисление ЗП · документ ZP-01')
    expect(linkedExpenseLabel({ module: 'external', id: 'EXT-9' })).toBe('Внешний платёж · ID EXT-9')
  })

  it('ignores API url and unsupported modules', () => {
    expect(
      linkedExpenseFrontendPath({
        module: 'cash',
        id: 9,
        url: 'https://example.com/api/cash/expenses/9/',
      }),
    ).toBe('/cash/expenses/9')
    expect(linkedExpenseFrontendPath({ module: 'corporate_card', id: 1 })).toBeNull()
    expect(linkedExpenseFrontendPath({ module: 'external', id: 'x' })).toBeNull()
    expect(canOpenLinkedExpense({ module: 'corporate_card', id: 1 })).toBe(false)
  })
})
