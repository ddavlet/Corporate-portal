import { describe, expect, it } from 'vitest'
import { formatAmount, formatDate, formatDelta, formatExact, formatRange, formatRatio, isFavorable } from './reportsFormat'

/** Intl uses non-breaking spaces between digit groups. */
const plain = (text: string) => text.replace(/[  ]/g, ' ')

describe('formatAmount', () => {
  it('scales to the chosen units', () => {
    expect(plain(formatAmount('1284134000.00', 'm'))).toBe('1 284,1')
    expect(plain(formatAmount('1234567.89', 'k'))).toBe('1 235')
    expect(plain(formatAmount('1234567.89', 'sum'))).toBe('1 234 568')
  })

  it('shows a dash for zero and for no data', () => {
    expect(formatAmount('0.00', 'm')).toBe('—')
    expect(formatAmount('40000.00', 'm')).toBe('—')
    expect(formatAmount(null, 'm')).toBe('—')
  })

  it('uses a real minus sign', () => {
    expect(formatAmount('-2500000', 'm')).toBe('−2,5')
  })
})

describe('formatExact and formatRatio', () => {
  it('shows kopecks only when present', () => {
    expect(plain(formatExact('98700000.00'))).toBe('98 700 000')
    expect(formatExact('10.50')).toBe('10,50')
  })

  it('formats margins as percent', () => {
    expect(formatRatio('0.8571')).toBe('85,7%')
    expect(formatRatio(null)).toBe('—')
    expect(formatRatio('-0.1234')).toBe('−12,3%')
    expect(formatRatio('-0.0001')).toBe('0,0%')
  })
})

describe('formatDelta and isFavorable', () => {
  it('formats percent and percentage points', () => {
    expect(formatDelta({ pct: '0.1850' })).toEqual({ text: '+18,5%', direction: 'up' })
    expect(formatDelta({ pp: '-3.4' })).toEqual({ text: '−3,4 п.п.', direction: 'down' })
    expect(formatDelta(null)).toBeNull()
  })

  it('treats expense growth as bad and neutral lines as no verdict', () => {
    expect(isFavorable('expense', 'up')).toBe(false)
    expect(isFavorable('income', 'up')).toBe(true)
    expect(isFavorable('result', 'down')).toBe(false)
    expect(isFavorable('neutral', 'up')).toBeNull()
  })
})

describe('formatRange and formatDate', () => {
  it('mirrors the backend range labels', () => {
    expect(formatRange('2026-08-01', '2026-08-31')).toBe('авг 2026')
    expect(formatRange('2026-09-01', '2026-09-23')).toBe('1–23 сен 2026')
    expect(formatRange('2026-01-01', '2026-09-23')).toBe('янв – 23 сен 2026')
    expect(formatRange('2025-01-01', '2025-12-31')).toBe('2025')
    expect(formatRange('2025-09-01', '2026-08-31')).toBe('сен 2025 – авг 2026')
  })

  it('formats ISO dates', () => {
    expect(formatDate('2026-09-23')).toBe('23.09.2026')
  })
})
