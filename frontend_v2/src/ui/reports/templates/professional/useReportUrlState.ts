import dayjs, { type Dayjs } from 'dayjs'
import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { ReportKind, StatementPeriod, StatementQuery } from '../../../../lib/reportsApi'
import { MONTH_NAMES, type Units } from '../../../../lib/reportsFormat'

/** A cell (`line`) or, with `vendor` and an empty line, one vendor's requests across every section. */
export type DrillTarget = { line: string; from: string; to: string; vendor?: string }
export type ReportView = 'statement' | 'operations'
/** Where «←» returns after a chart bar opened one month. */
export type ReportReturn = { period: StatementPeriod; year: number | null; month: string | null; granularity: 'month' | 'quarter' }

export type ReportUrlState = {
  report: ReportKind
  period: StatementPeriod
  year: number | null
  month: string | null
  granularity: 'month' | 'quarter'
  compare: 'none' | 'yoy'
  units: Units
  view: ReportView
  /** null = default (top-level sections open); [] = everything collapsed. */
  open: string[] | null
  drill: DrillTarget | null
  /** Only while the report is on one month. */
  back: ReportReturn | null
}

export const DEFAULT_REPORT_URL_STATE: ReportUrlState = {
  report: 'pnl',
  period: 'ytd',
  year: null,
  month: null,
  granularity: 'month',
  compare: 'yoy',
  units: 'm',
  view: 'statement',
  open: null,
  drill: null,
  back: null,
}

const MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/
const LINE_RE = /^[a-z_]+(\.[a-z0-9_]+)*$/
const KEYS = ['r', 'p', 'y', 'm', 'g', 'cmp', 'u', 'view', 'open', 'line', 'from', 'to', 'vendor', 'back']

function pick<T extends string>(raw: string | null, allowed: readonly T[], fallback: T): T {
  return raw !== null && (allowed as readonly string[]).includes(raw) ? (raw as T) : fallback
}

const PERIODS = ['month', 'ytd', 'year', 'ltm'] as const

/** `back=<period>,<year>,<month>,<granularity>`, e.g. `back=year,2025,,quarter`. */
function parseReturn(raw: string | null): ReportReturn | null {
  if (!raw) return null
  const [period, year, month, granularity] = raw.split(',')
  if (!(PERIODS as readonly string[]).includes(period)) return null
  const yearNumber = Number(year)
  return {
    period: period as StatementPeriod,
    year: year && Number.isInteger(yearNumber) && yearNumber >= 2000 && yearNumber <= 2100 ? yearNumber : null,
    month: month && MONTH_RE.test(month) ? month : null,
    granularity: granularity === 'quarter' ? 'quarter' : 'month',
  }
}

export function parseReportUrlState(params: URLSearchParams): ReportUrlState {
  const d = DEFAULT_REPORT_URL_STATE
  const year = Number(params.get('y'))
  const month = params.get('m')
  const open = params.get('open')
  const line = params.get('line')
  const from = params.get('from')
  const to = params.get('to')
  const vendor = (params.get('vendor') ?? '').trim().slice(0, 200)
  const lineOk = Boolean(line && LINE_RE.test(line))
  const datesOk = Boolean(from && to && DATE_RE.test(from) && DATE_RE.test(to))
  const period = pick(params.get('p'), PERIODS, d.period)
  return {
    report: pick(params.get('r'), ['pnl', 'cashflow'] as const, d.report),
    period,
    year: Number.isInteger(year) && year >= 2000 && year <= 2100 ? year : null,
    month: month && MONTH_RE.test(month) ? month : null,
    granularity: pick(params.get('g'), ['month', 'quarter'] as const, d.granularity),
    compare: pick(params.get('cmp'), ['none', 'yoy'] as const, d.compare),
    units: pick(params.get('u'), ['sum', 'k', 'm'] as const, d.units),
    view: pick(params.get('view'), ['statement', 'operations'] as const, d.view),
    open: open === null ? null : open.split(',').filter((id) => LINE_RE.test(id)),
    drill:
      datesOk && (lineOk || vendor)
        ? { line: lineOk ? (line as string) : '', from: from as string, to: to as string, ...(vendor ? { vendor } : {}) }
        : null,
    back: period === 'month' ? parseReturn(params.get('back')) : null,
  }
}

export function writeReportUrlState(base: URLSearchParams, state: ReportUrlState): URLSearchParams {
  const d = DEFAULT_REPORT_URL_STATE
  const next = new URLSearchParams(base)
  for (const key of KEYS) next.delete(key)
  if (state.report !== d.report) next.set('r', state.report)
  if (state.period !== d.period) next.set('p', state.period)
  if (state.year !== null) next.set('y', String(state.year))
  if (state.month) next.set('m', state.month)
  if (state.granularity !== d.granularity) next.set('g', state.granularity)
  if (state.compare !== d.compare) next.set('cmp', state.compare)
  if (state.units !== d.units) next.set('u', state.units)
  if (state.view !== d.view) next.set('view', state.view)
  if (state.open !== null) next.set('open', state.open.join(','))
  if (state.drill) {
    if (state.drill.line) next.set('line', state.drill.line)
    next.set('from', state.drill.from)
    next.set('to', state.drill.to)
    if (state.drill.vendor) next.set('vendor', state.drill.vendor)
  }
  if (state.back && state.period === 'month') {
    const { period, year, month, granularity } = state.back
    next.set('back', [period, year ?? '', month ?? '', granularity].join(','))
  }
  return next
}

/** «С начала года», «2025 год», «Последние 12 месяцев», «Июль 2026». */
export function returnLabel(back: ReportReturn, today: Dayjs = dayjs()): string {
  if (back.period === 'ytd') return 'С начала года'
  if (back.period === 'ltm') return 'Последние 12 месяцев'
  if (back.period === 'year') return `${back.year ?? today.year()} год`
  const month = effectiveMonth({ ...DEFAULT_REPORT_URL_STATE, month: back.month }, today)
  return `${MONTH_NAMES[Number(month.slice(5, 7)) - 1]} ${month.slice(0, 4)}`
}

/** The monthly report defaults to the last closed month. */
export function defaultReportMonth(today: Dayjs = dayjs()): string {
  return today.subtract(1, 'month').format('YYYY-MM')
}

/** The month the report shows: the one in the link unless it has not started yet, then the last closed month. */
export function effectiveMonth(state: ReportUrlState, today: Dayjs = dayjs()): string {
  return state.month && state.month <= today.format('YYYY-MM') ? state.month : defaultReportMonth(today)
}

/** The year the report shows: the one in the link unless it has not started yet, then the current year. */
export function effectiveYear(state: ReportUrlState, today: Dayjs = dayjs()): number {
  return state.year !== null && state.year <= today.year() ? state.year : today.year()
}

export function toStatementQuery(template: string, state: ReportUrlState, today: Dayjs = dayjs()): StatementQuery {
  const base = { template, report: state.report, period: state.period }
  if (state.period === 'month') return { ...base, month: effectiveMonth(state, today) }
  return {
    ...base,
    ...(state.period === 'year' ? { year: effectiveYear(state, today) } : {}),
    granularity: state.granularity,
    compare: state.compare,
  }
}

export function useReportUrlState(): [ReportUrlState, (patch: Partial<ReportUrlState>) => void] {
  const [params, setParams] = useSearchParams()
  const state = useMemo(() => parseReportUrlState(params), [params])
  const update = useCallback(
    (patch: Partial<ReportUrlState>) => {
      setParams((prev) => writeReportUrlState(prev, { ...parseReportUrlState(prev), ...patch }), { replace: true })
    },
    [setParams],
  )
  return [state, update]
}
