import dayjs from 'dayjs'
import { describe, expect, it } from 'vitest'
import {
  DEFAULT_REPORT_URL_STATE,
  parseReportUrlState,
  returnLabel,
  toStatementQuery,
  writeReportUrlState,
} from './useReportUrlState'

describe('parseReportUrlState', () => {
  it('uses defaults for an empty URL', () => {
    expect(parseReportUrlState(new URLSearchParams())).toEqual(DEFAULT_REPORT_URL_STATE)
  })

  it('reads every key', () => {
    const state = parseReportUrlState(
      new URLSearchParams('p=month&m=2026-08&g=quarter&cmp=none&u=k&view=operations&open=rev,opex&line=opex.1a2b3c4d&from=2026-08-01&to=2026-08-31'),
    )
    expect(state).toEqual({
      period: 'month',
      year: null,
      month: '2026-08',
      granularity: 'quarter',
      compare: 'none',
      units: 'k',
      view: 'operations',
      open: ['rev', 'opex'],
      drill: { line: 'opex.1a2b3c4d', from: '2026-08-01', to: '2026-08-31' },
      back: null,
    })
  })

  it('falls back to defaults for invalid values', () => {
    const state = parseReportUrlState(new URLSearchParams('r=x&p=weird&y=1800&m=2026-13&u=bn&line=../x&from=2026-08-01&to=2026-08-31'))
    expect(state).toEqual(DEFAULT_REPORT_URL_STATE)
  })

  it('keeps an explicitly empty open list', () => {
    expect(parseReportUrlState(new URLSearchParams('open=')).open).toEqual([])
  })
})

describe('writeReportUrlState', () => {
  it('omits defaults and keeps unrelated keys', () => {
    const next = writeReportUrlState(new URLSearchParams('t=professional&p=ltm'), DEFAULT_REPORT_URL_STATE)
    expect(next.toString()).toBe('t=professional')
  })

  it('round-trips a full state', () => {
    const state = parseReportUrlState(new URLSearchParams('p=year&y=2025&u=sum&open=&line=rev&from=2025-01-01&to=2025-12-31'))
    expect(parseReportUrlState(writeReportUrlState(new URLSearchParams(), state))).toEqual(state)
  })
})

describe('toStatementQuery', () => {
  const today = dayjs('2026-09-23')

  it('defaults the month pack to the last closed month', () => {
    const state = { ...DEFAULT_REPORT_URL_STATE, period: 'month' as const }
    expect(toStatementQuery('professional', 'pnl', state, today)).toEqual({ template: 'professional', report: 'pnl', period: 'month', month: '2026-08' })
  })

  it('defaults the year to the current one and passes columns and comparison', () => {
    const state = { ...DEFAULT_REPORT_URL_STATE, period: 'year' as const, granularity: 'quarter' as const }
    expect(toStatementQuery('professional', 'pnl', state, today)).toEqual({
      template: 'professional',
      report: 'pnl',
      period: 'year',
      year: 2026,
      granularity: 'quarter',
      compare: 'yoy',
    })
  })

  it('never asks for a month or year that has not started', () => {
    const today = dayjs('2026-09-23')
    const month = (value: string) =>
      toStatementQuery('professional', 'pnl', { ...DEFAULT_REPORT_URL_STATE, period: 'month', month: value }, today).month
    expect(month('2027-01')).toBe('2026-08')
    expect(month('2026-09')).toBe('2026-09')
    expect(toStatementQuery('professional', 'pnl', { ...DEFAULT_REPORT_URL_STATE, period: 'year', year: 2099 }, today).year).toBe(2026)
  })

  it('asks for the report it is given', () => {
    expect(toStatementQuery('professional', 'cashflow', DEFAULT_REPORT_URL_STATE, today).report).toBe('cashflow')
  })
})

describe('vendor drill-down', () => {
  it('reads a vendor panel without a line', () => {
    const state = parseReportUrlState(new URLSearchParams('from=2026-08-01&to=2026-08-31&vendor=%D0%9E%D0%9E%D0%9E%20%D0%9E%D1%84%D0%B8%D1%81'))
    expect(state.drill).toEqual({ line: '', from: '2026-08-01', to: '2026-08-31', vendor: 'ООО Офис' })
  })

  it('ignores dates without a line or a vendor', () => {
    expect(parseReportUrlState(new URLSearchParams('from=2026-08-01&to=2026-08-31')).drill).toBeNull()
  })

  it('writes the vendor and leaves the line out', () => {
    const next = writeReportUrlState(new URLSearchParams(), {
      ...DEFAULT_REPORT_URL_STATE,
      drill: { line: '', from: '2026-08-01', to: '2026-08-31', vendor: 'ООО Офис' },
    })
    expect(next.get('vendor')).toBe('ООО Офис')
    expect(next.has('line')).toBe(false)
    expect(parseReportUrlState(next).drill).toEqual({ line: '', from: '2026-08-01', to: '2026-08-31', vendor: 'ООО Офис' })
  })
})

describe('return from a month opened on the chart', () => {
  it('keeps where to go back to in the link, so a reload keeps the button', () => {
    const state = parseReportUrlState(new URLSearchParams('p=month&m=2026-08&back=year,2025,,quarter'))
    expect(state.back).toEqual({ period: 'year', year: 2025, month: null, granularity: 'quarter' })
    expect(parseReportUrlState(writeReportUrlState(new URLSearchParams(), state)).back).toEqual(state.back)
  })

  it('forgets it once the report is no longer on one month', () => {
    expect(parseReportUrlState(new URLSearchParams('p=ytd&back=year,2025,,month')).back).toBeNull()
    const moved = { ...parseReportUrlState(new URLSearchParams('p=month&m=2026-08&back=ytd,,,month')), period: 'ltm' as const }
    expect(writeReportUrlState(new URLSearchParams(), moved).has('back')).toBe(false)
  })

  it('ignores a broken value', () => {
    expect(parseReportUrlState(new URLSearchParams('p=month&back=weird,x,y,z')).back).toBeNull()
  })

  it('names the period it returns to', () => {
    const today = dayjs('2026-09-23')
    const back = (period: 'ytd' | 'year' | 'ltm' | 'month', year: number | null = null, month: string | null = null) => ({ period, year, month, granularity: 'month' as const })
    expect(returnLabel(back('ytd'), today)).toBe('С начала года')
    expect(returnLabel(back('year', 2025), today)).toBe('2025 год')
    expect(returnLabel(back('year'), today)).toBe('2026 год')
    expect(returnLabel(back('ltm'), today)).toBe('Последние 12 месяцев')
    expect(returnLabel(back('month', null, '2026-07'), today)).toBe('Июль 2026')
  })
})
