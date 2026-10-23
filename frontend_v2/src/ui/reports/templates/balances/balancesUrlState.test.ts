import dayjs from 'dayjs'
import { describe, expect, it } from 'vitest'
import { isReportKind } from '../../../../lib/reportsApi'
import { countLabel } from './balancesFormat'
import { readBalancesState, toBalancesQuery, writeBalancesState } from './balancesUrlState'

const today = dayjs('2026-10-23')

describe('readBalancesState', () => {
  it('defaults to this month up to today', () => {
    expect(readBalancesState(new URLSearchParams(), today)).toEqual({
      mode: 'period',
      wallet: null,
      start: '2026-10-01',
      end: '2026-10-23',
    })
  })

  it('ignores broken dates and a start after the end', () => {
    const state = readBalancesState(new URLSearchParams('start=2026-09-31&end=2026-09-10&wallet=x'), today)
    expect(state).toEqual({ mode: 'period', wallet: null, start: '2026-09-01', end: '2026-09-10' })
    expect(readBalancesState(new URLSearchParams('start=2026-09-20&end=2026-09-10'), today).start).toBe('2026-09-10')
  })
})

describe('toBalancesQuery', () => {
  it('sends no start in «На дату»: the backend counts from the first operation', () => {
    const state = readBalancesState(new URLSearchParams('mode=date&end=2026-05-31&start=2026-05-01&wallet=7'), today)
    expect(toBalancesQuery({ ...state, wallet: 7 })).toEqual({ wallet: 7, dateTo: '2026-05-31', dateFrom: undefined })
  })

  it('round-trips through the address bar', () => {
    const state = { mode: 'period' as const, wallet: 3, start: '2026-03-01', end: '2026-03-31' }
    expect(readBalancesState(writeBalancesState(new URLSearchParams('keep=1'), state), today)).toEqual(state)
  })
})

describe('balances helpers', () => {
  it('declines «операция»', () => {
    expect([1, 2, 5, 11, 21, 104].map(countLabel)).toEqual([
      '1 операция',
      '2 операции',
      '5 операций',
      '11 операций',
      '21 операция',
      '104 операции',
    ])
  })

  it('treats only statement reports as reports with rules', () => {
    expect(['pnl', 'cashflow', 'balances'].map(isReportKind)).toEqual([true, true, false])
  })
})
