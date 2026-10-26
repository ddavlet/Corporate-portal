import { describe, expect, it } from 'vitest'

import { totalsInBothCurrencies } from './utils'

describe('totalsInBothCurrencies', () => {
  it('складывает заявки в разных валютах в общий итог USD/UZS по эквивалентам', () => {
    const rows = [
      { currency: 'USD', amount: '1000', sum_usd: '1000.00', sum_uzs: '12600000.00' },
      { currency: 'UZS', amount: '12600000', sum_usd: '1000.00', sum_uzs: '12600000.00' },
    ]
    expect(totalsInBothCurrencies(rows)).toEqual([
      { currency: 'USD', total: 2000 },
      { currency: 'UZS', total: 25200000 },
    ])
  })

  it('строки без курса (null) не ломают итог', () => {
    const rows = [
      { currency: 'USD', sum_usd: '500', sum_uzs: '6300000' },
      { currency: 'EUR', sum_usd: null, sum_uzs: null },
    ]
    expect(totalsInBothCurrencies(rows)).toEqual([
      { currency: 'USD', total: 500 },
      { currency: 'UZS', total: 6300000 },
    ])
  })
})
