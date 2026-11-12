import { describe, expect, it } from 'vitest'

import type { FundingPoolRequestDto } from '../../lib/api'
import {
  defaultCollectComment,
  fundingTotalLine,
  fundingTotalsText,
  groupByKind,
  totalsByCurrency,
} from './fundingPool'

function row(over: Partial<FundingPoolRequestDto>): FundingPoolRequestDto {
  return {
    id: 1,
    submitted_at: '2026-10-01T10:00:00Z',
    kind: 'expense',
    payment_type: 'Наличные',
    payment_purpose: '',
    description: '',
    amount: '1000',
    currency: 'UZS',
    status: 'approved',
    is_payed: false,
    ...over,
  }
}

const rows = [
  row({ id: 1, amount: '5000000', currency: 'UZS' }),
  row({ id: 2, amount: '2000000', currency: 'UZS' }),
  row({ id: 3, amount: '100', currency: 'USD' }),
]

describe('totalsByCurrency', () => {
  it('sums selected rows per currency', () => {
    expect(totalsByCurrency(rows, new Set([1, 2, 3]))).toEqual([
      { currency: 'UZS', amount: 7000000, count: 2 },
      { currency: 'USD', amount: 100, count: 1 },
    ])
  })

  it('ignores deselected rows', () => {
    expect(totalsByCurrency(rows, new Set([1, 3]))[0]).toEqual({ currency: 'UZS', amount: 5000000, count: 1 })
  })
})

describe('defaultCollectComment', () => {
  it('matches the backend format for expense and transfer', () => {
    const list = [
      row({ id: 123, description: 'компьютер' }),
      row({ id: 124, kind: 'transfer', payment_purpose: 'Перевод между кассами' }),
    ]
    expect(defaultCollectComment(list)).toBe(
      'На основании заявок №123, №124. №123 — компьютер; №124 — перевод между кассами',
    )
  })

  it('uses singular title, falls back to purpose and omits empty notes', () => {
    expect(defaultCollectComment([row({ id: 5, payment_purpose: 'Закупка' })])).toBe(
      'На основании заявки №5. №5 — Закупка',
    )
    expect(defaultCollectComment([row({ id: 6 })])).toBe('На основании заявки №6.')
    expect(defaultCollectComment([])).toBe('')
  })

  it('truncates long notes to 80 characters', () => {
    const out = defaultCollectComment([row({ id: 7, description: 'я'.repeat(200) })])
    expect(out).toBe(`На основании заявки №7. №7 — ${'я'.repeat(80)}`)
  })
})

describe('groupByKind', () => {
  it('splits expenses and transfers', () => {
    const g = groupByKind([row({ id: 1 }), row({ id: 2, kind: 'transfer' })])
    expect(g.expense.map((r) => r.id)).toEqual([1])
    expect(g.transfer.map((r) => r.id)).toEqual([2])
  })
})

describe('fundingTotalLine', () => {
  const line = (count: number) => fundingTotalLine({ currency: 'UZS', amount: 1000, count })

  it('declines «заявка» by the count', () => {
    expect(line(1)).toMatch(/\(1 заявка\)$/)
    expect(line(2)).toMatch(/\(2 заявки\)$/)
    expect(line(5)).toMatch(/\(5 заявок\)$/)
    expect(line(11)).toMatch(/\(11 заявок\)$/)
    expect(line(21)).toMatch(/\(21 заявка\)$/)
    expect(line(22)).toMatch(/\(22 заявки\)$/)
  })

  it('formats the amount and the currency', () => {
    expect(fundingTotalLine({ currency: 'UZS', amount: 5000000, count: 1 })).toMatch(/^5\s?000\s?000 UZS \(1 заявка\)$/)
  })
})

describe('fundingTotalsText', () => {
  it('says that nothing is selected for an empty list', () => {
    expect(fundingTotalsText([])).toBe('Итого: ничего не выбрано')
  })

  it('joins two currencies with «; »', () => {
    expect(
      fundingTotalsText([
        { currency: 'UZS', amount: 7000000, count: 2 },
        { currency: 'USD', amount: 100, count: 1 },
      ]),
    ).toMatch(/^Итого: 7\s?000\s?000 UZS \(2 заявки\); 100 USD \(1 заявка\)$/)
  })
})
