import dayjs from 'dayjs'
import { describe, expect, it } from 'vitest'
import {
  DEFAULT_REPORT_URL_STATE,
  parseReportUrlState,
  toStatementQuery,
  writeReportUrlState,
} from './useReportUrlState'

describe('parseReportUrlState', () => {
  it('uses defaults for an empty URL', () => {
    expect(parseReportUrlState(new URLSearchParams())).toEqual(DEFAULT_REPORT_URL_STATE)
  })

  it('reads every key', () => {
    const state = parseReportUrlState(
      new URLSearchParams('r=cashflow&p=month&m=2026-08&g=quarter&cmp=none&u=k&view=operations&open=rev,opex&line=opex.1a2b3c4d&from=2026-08-01&to=2026-08-31'),
    )
    expect(state).toEqual({
      report: 'cashflow',
      period: 'month',
      year: null,
      month: '2026-08',
      granularity: 'quarter',
      compare: 'none',
      units: 'k',
      view: 'operations',
      open: ['rev', 'opex'],
      drill: { line: 'opex.1a2b3c4d', from: '2026-08-01', to: '2026-08-31' },
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
    const state = parseReportUrlState(new URLSearchParams('r=cashflow&p=year&y=2025&u=sum&open=&line=rev&from=2025-01-01&to=2025-12-31'))
    expect(parseReportUrlState(writeReportUrlState(new URLSearchParams(), state))).toEqual(state)
  })
})

describe('toStatementQuery', () => {
  const today = dayjs('2026-09-23')

  it('defaults the month pack to the last closed month', () => {
    const state = { ...DEFAULT_REPORT_URL_STATE, period: 'month' as const }
    expect(toStatementQuery('professional', state, today)).toEqual({ template: 'professional', report: 'pnl', period: 'month', month: '2026-08' })
  })

  it('defaults the year to the current one and passes columns and comparison', () => {
    const state = { ...DEFAULT_REPORT_URL_STATE, period: 'year' as const, granularity: 'quarter' as const }
    expect(toStatementQuery('professional', state, today)).toEqual({
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
      toStatementQuery('professional', { ...DEFAULT_REPORT_URL_STATE, period: 'month', month: value }, today).month
    expect(month('2027-01')).toBe('2026-08')
    expect(month('2026-09')).toBe('2026-09')
    expect(toStatementQuery('professional', { ...DEFAULT_REPORT_URL_STATE, period: 'year', year: 2099 }, today).year).toBe(2026)
  })
})
