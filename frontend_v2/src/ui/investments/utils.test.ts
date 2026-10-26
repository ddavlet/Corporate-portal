import { describe, expect, it } from 'vitest'

import { staleCbuRateDate, totalsInBothCurrencies } from './utils'

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

describe('staleCbuRateDate', () => {
  const today = '2026-10-26'

  it('null, когда все строки посчитаны по курсу на свою дату или без эквивалентов', () => {
    const rows = [
      { date: '2026-10-20', rate_date: '2026-10-20' },
      { date: '2026-10-21', rate_date: null },
    ]
    expect(staleCbuRateDate(rows, today)).toBeNull()
  })

  it('самая поздняя дата курса среди строк с курсом не на их дату', () => {
    const rows = [
      { date: '2026-10-10', rate_date: '2026-10-08' },
      { date: '2026-10-25', rate_date: '2026-10-22' },
      { date: '2026-10-20', rate_date: '2026-10-20' },
    ]
    expect(staleCbuRateDate(rows, today)).toBe('2026-10-22')
  })

  it('строку с будущей датой сравнивает с сегодняшним днём', () => {
    expect(staleCbuRateDate([{ date: '2026-11-05', rate_date: today }], today)).toBeNull()
    expect(staleCbuRateDate([{ date: '2026-11-05', rate_date: '2026-10-25' }], today)).toBe('2026-10-25')
  })
})
