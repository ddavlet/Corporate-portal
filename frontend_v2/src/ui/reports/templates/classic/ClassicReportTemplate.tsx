import { useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Card, DatePicker, Descriptions, Input, Segmented, Skeleton, Space, Table, Tag, Tooltip, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  getStructuredCashflowReport,
  getStructuredPnlReport,
  type LegacyReportItem,
  type StructuredReportPayload,
  type StructuredReportRow,
} from '../../../../lib/api'
import type { ReportKind } from '../../../../lib/reportsApi'
import {
  filterForMatrixRow,
  operationRowKey,
  operationsFilterCaption,
  rowMatchesSection,
  vendorOf,
  type OperationsFilter,
  type ReportSection,
} from './reportsOperationsFilter'
import { dateFromParam, yearFromParam } from './classicUrlState'
import type { ReportTemplateProps } from '../types'

/** One loader per report: the page asks only for the report of its card. */
const LOADERS: Record<ReportKind, () => Promise<StructuredReportPayload>> = {
  pnl: getStructuredPnlReport,
  cashflow: getStructuredCashflowReport,
}

const REPORT_NAMES: Record<ReportKind, string> = { pnl: 'PnL', cashflow: 'Cashflow' }

type MatrixRow = {
  key: string
  label: string
  kind: 'section' | 'revenue' | 'expense' | 'summary'
  values: number[]
  emphasize?: boolean
}

type KeyedReportRow = StructuredReportRow & { rowKey: string }

const moneyFmt = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const REPORT_TZ = 'Asia/Tashkent'
/** How long the search box waits after the last keystroke before it writes the search to the link. */
const SEARCH_LINK_DELAY_MS = 300
const monthFmt = new Intl.DateTimeFormat('ru-RU', { month: 'short' })
const MONTH_LABELS = Array.from({ length: 12 }, (_, i) => {
  const s = monthFmt.format(new Date(2000, i, 1))
  return s.charAt(0).toUpperCase() + s.slice(1).replace('.', '')
})

/** Календарный год в зоне отчёта (как у дат операций). */
function currentReportCalendarYear(date = new Date()): number {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: REPORT_TZ,
    year: 'numeric',
  }).formatToParts(date)
  const y = Number(parts.find((p) => p.type === 'year')?.value ?? '')
  return Number.isFinite(y) ? y : date.getFullYear()
}

function roundToCents(value: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.round(value * 100) / 100
}

function money(value: string | number): string {
  const raw = typeof value === 'number' ? value : Number(String(value).replace(/\s+/g, '').replace(',', '.'))
  if (!Number.isFinite(raw)) return moneyFmt.format(0)
  return moneyFmt.format(roundToCents(raw))
}

/** Длина строки как в ячейке матрицы (скобки для отрицательных). */
function matrixCellMoneyDisplayLength(value: number): number {
  if (roundToCents(value) === 0) return money(0).length
  const t = money(Math.abs(value))
  return value < 0 ? t.length + 2 : t.length
}

function maxMatrixMonthMoneyDisplayLen(matrixRows: MatrixRow[]): number {
  let maxLen = 4
  for (const row of matrixRows) {
    if (row.kind === 'section') continue
    for (let m = 0; m < 12; m++) {
      maxLen = Math.max(maxLen, matrixCellMoneyDisplayLength(row.values[m] ?? 0))
    }
  }
  return maxLen
}

/** Ширина колонки месяца в px: вмещает форматированную сумму без переноса. */
function moneyColumnWidthFromMaxChars(maxChars: number): number {
  return Math.min(Math.max(Math.ceil(maxChars * 7.2) + 36, 92), 280)
}

function maxAmountStringLen(rows: StructuredReportRow[]): number {
  let maxLen = 5
  for (const row of rows) {
    const t = money(row.amount)
    maxLen = Math.max(maxLen, t.length)
  }
  return maxLen
}

function dateText(value?: string | null): string {
  if (!value) return '-'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '-'
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    timeZone: 'Asia/Tashkent',
  }).format(d)
}

function parseAmount(value: unknown): number {
  if (typeof value === 'number') return Number.isFinite(value) ? value : 0
  if (typeof value !== 'string') return 0
  const normalized = value.replace(/\s+/g, '').replace(',', '.')
  const parsed = Number(normalized)
  return Number.isFinite(parsed) ? parsed : 0
}

function parseMonthRef(input: unknown): { year: number; monthIndex: number } | null {
  if (typeof input !== 'string' || !input.trim()) return null
  const parsed = new Date(input.trim().replace(/^"+|"+$/g, ''))
  if (Number.isNaN(parsed.getTime())) return null
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: REPORT_TZ,
    year: 'numeric',
    month: '2-digit',
  }).formatToParts(parsed)
  const year = Number(parts.find((p) => p.type === 'year')?.value ?? '')
  const monthIndex = Number(parts.find((p) => p.type === 'month')?.value ?? '') - 1
  if (!Number.isFinite(year) || monthIndex < 0 || monthIndex > 11) return null
  return { year, monthIndex }
}

function parseYmStartMonth(raw: unknown): string | null {
  if (typeof raw !== 'string') return null
  const t = raw.trim()
  if (!/^\d{4}-\d{2}$/.test(t)) return null
  return t
}

/** Год-месяц для колонки матрицы (monthIndex 0 = январь). */
function ymKey(year: number, monthIndex: number): string {
  return `${year}-${String(monthIndex + 1).padStart(2, '0')}`
}

function addOneYm(key: string): string {
  const [yStr, mStr] = key.split('-')
  let y = Number(yStr)
  let m = Number(mStr)
  if (!Number.isFinite(y) || !Number.isFinite(m)) return key
  m += 1
  if (m > 12) {
    m = 1
    y += 1
  }
  return `${y}-${String(m).padStart(2, '0')}`
}

/** Сводка «остаток» по календарным месяцам (доход − расходы − инвествыплаты), по всем годам в данных. */
function accumulateNetBalanceByYm(report: StructuredReportPayload): Record<string, number> {
  const byYm: Record<string, number> = {}
  const bump = (dateStr: string | undefined | null, delta: number) => {
    const ref = parseMonthRef(dateStr)
    if (!ref) return
    const k = ymKey(ref.year, ref.monthIndex)
    byYm[k] = roundToCents((byYm[k] ?? 0) + delta)
  }

  for (const row of report.revenue ?? []) {
    bump(row.date, roundToCents(Math.abs(parseAmount(row.amount ?? row.kredit))))
  }

  const operationalSource = (report.operational_expenses?.length ?? 0) > 0 ? report.operational_expenses : []
  const otherSource =
    (report.other_expenses?.length ?? 0) > 0
      ? report.other_expenses
      : (report.operational_expenses?.length ?? 0) === 0 && (report.expense?.length ?? 0) > 0
        ? report.expense
        : []

  for (const row of operationalSource) {
    bump(row.date, roundToCents(-Math.abs(parseAmount(row.amount ?? row.kredit))))
  }

  for (const row of otherSource) {
    bump(row.date, roundToCents(-Math.abs(parseAmount(row.amount ?? row.kredit))))
  }

  for (const row of report.invest_returns ?? []) {
    bump(row.date, roundToCents(-Math.abs(parseAmount(row.amount ?? row.kredit))))
  }

  return byYm
}

function cumulativeBalanceFromStartParams(opts: {
  balanceByYm: Record<string, number>
  effectiveYear: number
  startYm: string | null
  opening: number
}): number[] {
  const { balanceByYm, effectiveYear, startYm, opening } = opts
  const cumulative = Array(12).fill(0) as number[]
  if (!startYm) {
    let running = roundToCents(opening)
    for (let m = 0; m < 12; m++) {
      running = roundToCents(running + (balanceByYm[ymKey(effectiveYear, m)] ?? 0))
      cumulative[m] = running
    }
    return cumulative
  }

  for (let m = 0; m < 12; m++) {
    const cellKey = ymKey(effectiveYear, m)
    if (cellKey.localeCompare(startYm) < 0) {
      cumulative[m] = 0
      continue
    }
    let total = roundToCents(opening)
    for (let k = startYm; k.localeCompare(cellKey) <= 0; k = addOneYm(k)) {
      total = roundToCents(total + (balanceByYm[k] ?? 0))
    }
    cumulative[m] = total
  }
  return cumulative
}

function categoryFromItem(item: LegacyReportItem): string {
  return (
    item.category ||
    item.cathegory ||
    item.cat ||
    item.cat_name ||
    item.article ||
    item.item ||
    item.purpose ||
    item.description ||
    'Без категории'
  )
}

type MonthSelection = {
  year: number
  monthIndex: number
}

function normalizeCategoryFromFields(source: {
  category?: unknown
  cathegory?: unknown
  cat?: unknown
  cat_name?: unknown
  article?: unknown
  item?: unknown
  purpose?: unknown
  description?: unknown
}): string {
  const values = [
    source.category,
    source.cathegory,
    source.cat,
    source.cat_name,
    source.article,
    source.item,
    source.purpose,
    source.description,
  ]
  for (const value of values) {
    const text = String(value ?? '').trim()
    if (text) return text
  }
  return 'Без категории'
}

function categoryFromStructuredRow(row: StructuredReportRow): string {
  return normalizeCategoryFromFields({
    category: row.category,
    purpose: row.purpose,
    description: row.description,
    ...(row.raw ?? {}),
  })
}

function resolveRequestIdFromPnlExpenseRow(row: StructuredReportRow): number | null {
  const raw = (row.raw ?? {}) as Record<string, unknown>
  const candidate = raw.request_id ?? row.id
  const value = Number(String(candidate ?? '').trim())
  if (!Number.isInteger(value) || value <= 0) return null
  return value
}

function buildLegacyMatrix(report: StructuredReportPayload | null, year: number | null): { months: number[]; rows: MatrixRow[]; years: number[] } {
  if (!report) return { months: [], rows: [], years: [] }
  const yearsSet = new Set<number>()
  for (const row of [
    ...(report.revenue ?? []),
    ...(report.operational_expenses ?? []),
    ...(report.other_expenses ?? []),
    ...(report.expense ?? []),
    ...(report.invest_returns ?? []),
  ]) {
    const ref = parseMonthRef(row.date)
    if (ref) yearsSet.add(ref.year)
  }
  const years = Array.from(yearsSet).sort((a, b) => a - b)
  const effectiveYear = year ?? currentReportCalendarYear()
  const months = Array.from({ length: 12 }, (_, i) => i)

  const revByCat = new Map<string, number[]>()
  const operationalExpByCat = new Map<string, number[]>()
  const otherExpByCat = new Map<string, number[]>()
  const revTotals = Array(12).fill(0) as number[]
  const operationalExpTotals = Array(12).fill(0) as number[]
  const otherExpTotals = Array(12).fill(0) as number[]
  const investReturnsTotals = Array(12).fill(0) as number[]

  for (const row of report.revenue ?? []) {
    const ref = parseMonthRef(row.date)
    if (!ref || ref.year !== effectiveYear) continue
    const amount = roundToCents(Math.abs(parseAmount(row.amount ?? row.kredit)))
    const category = categoryFromItem(row)
    const bucket = revByCat.get(category) ?? Array(12).fill(0)
    bucket[ref.monthIndex] = roundToCents(bucket[ref.monthIndex] + amount)
    revTotals[ref.monthIndex] = roundToCents(revTotals[ref.monthIndex] + amount)
    revByCat.set(category, bucket)
  }

  const operationalSource = (report.operational_expenses?.length ?? 0) > 0 ? report.operational_expenses : []
  const otherSource =
    (report.other_expenses?.length ?? 0) > 0
      ? report.other_expenses
      : (report.operational_expenses?.length ?? 0) === 0 && (report.expense?.length ?? 0) > 0
        ? report.expense
        : []

  for (const row of operationalSource) {
    const ref = parseMonthRef(row.date)
    if (!ref || ref.year !== effectiveYear) continue
    const amount = roundToCents(Math.abs(parseAmount(row.amount ?? row.kredit)))
    const category = categoryFromItem(row)
    const bucket = operationalExpByCat.get(category) ?? Array(12).fill(0)
    bucket[ref.monthIndex] = roundToCents(bucket[ref.monthIndex] - amount)
    operationalExpTotals[ref.monthIndex] = roundToCents(operationalExpTotals[ref.monthIndex] - amount)
    operationalExpByCat.set(category, bucket)
  }

  for (const row of otherSource) {
    const ref = parseMonthRef(row.date)
    if (!ref || ref.year !== effectiveYear) continue
    const amount = roundToCents(Math.abs(parseAmount(row.amount ?? row.kredit)))
    const category = categoryFromItem(row)
    const bucket = otherExpByCat.get(category) ?? Array(12).fill(0)
    bucket[ref.monthIndex] = roundToCents(bucket[ref.monthIndex] - amount)
    otherExpTotals[ref.monthIndex] = roundToCents(otherExpTotals[ref.monthIndex] - amount)
    otherExpByCat.set(category, bucket)
  }

  for (const row of report.invest_returns ?? []) {
    const ref = parseMonthRef(row.date)
    if (!ref || ref.year !== effectiveYear) continue
    const amount = roundToCents(Math.abs(parseAmount(row.amount ?? row.kredit)))
    investReturnsTotals[ref.monthIndex] = roundToCents(investReturnsTotals[ref.monthIndex] - amount)
  }

  const sortByAbsTotalDesc = (a: [string, number[]], b: [string, number[]]) => {
    const sumA = a[1].reduce((s, x) => s + Math.abs(x), 0)
    const sumB = b[1].reduce((s, x) => s + Math.abs(x), 0)
    return sumB - sumA
  }

  const sortCategoryAz = (a: [string, number[]], b: [string, number[]]) =>
    a[0].localeCompare(b[0], 'ru', { sensitivity: 'base' })

  const revenueRows: MatrixRow[] = Array.from(revByCat.entries())
    .sort(sortByAbsTotalDesc)
    .map(([label, values]) => ({ key: `rev:${label}`, label, kind: 'revenue', values }))

  const operationalExpenseRows: MatrixRow[] = Array.from(operationalExpByCat.entries())
    .sort(sortCategoryAz)
    .map(([label, values]) => ({ key: `exp:op:${label}`, label, kind: 'expense', values }))

  const otherExpenseRows: MatrixRow[] = Array.from(otherExpByCat.entries())
    .sort(sortCategoryAz)
    .map(([label, values]) => ({ key: `exp:other:${label}`, label, kind: 'expense', values }))

  const ebit = revTotals.map((v, idx) => roundToCents(v + operationalExpTotals[idx]))
  const net = ebit.map((v, idx) => roundToCents(v + otherExpTotals[idx]))
  const balanceByYm = accumulateNetBalanceByYm(report)
  const balance = Array.from({ length: 12 }, (_, idx) => roundToCents(balanceByYm[ymKey(effectiveYear, idx)] ?? 0))
  const startYm =
    parseYmStartMonth(report.report_settings?.start_month) ?? parseYmStartMonth(report.metadata?.start_month ?? null)
  const opening = parseAmount(report.report_settings?.opening_balance ?? report.totals?.opening_balance)
  const cumulative = cumulativeBalanceFromStartParams({
    balanceByYm,
    effectiveYear,
    startYm,
    opening,
  })

  const rows: MatrixRow[] = [
    { key: 'section:income', label: 'Доходы', kind: 'section', values: Array(12).fill(0), emphasize: true },
    ...revenueRows,
    { key: 'sum:income', label: 'Итого доходы', kind: 'summary', values: revTotals, emphasize: true },
    { key: 'section:operational-expense', label: 'Операционные расходы', kind: 'section', values: Array(12).fill(0), emphasize: true },
    ...operationalExpenseRows,
    { key: 'sum:operational-expense', label: 'Итого операционные расходы', kind: 'summary', values: operationalExpTotals, emphasize: true },
    { key: 'sum:ebit', label: 'EBIT', kind: 'summary', values: ebit, emphasize: true },
    { key: 'section:other-expense', label: 'Прочие расходы', kind: 'section', values: Array(12).fill(0), emphasize: true },
    ...otherExpenseRows,
    { key: 'sum:other-expense', label: 'Итого прочие расходы', kind: 'summary', values: otherExpTotals, emphasize: true },
    { key: 'sum:net', label: 'Чистая прибыль', kind: 'summary', values: net, emphasize: true },
    {
      key: 'sum:invest_returns',
      label: 'Выплаты по инвестициям',
      kind: 'summary',
      values: investReturnsTotals,
      emphasize: true,
    },
    { key: 'sum:balance', label: 'Остаток', kind: 'summary', values: balance, emphasize: true },
    { key: 'sum:cumulative', label: 'Суммарный остаток (начальный остаток + месяцы с start_month)', kind: 'summary', values: cumulative, emphasize: true },
  ]

  return { months, rows, years }
}

export function ClassicReportTemplate({ report, rulesVersion }: ReportTemplateProps) {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const operationsCardRef = useRef<HTMLDivElement | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [payload, setPayload] = useState<StructuredReportPayload | null>(null)
  const [selectedDirection, setSelectedDirection] = useState<'revenue' | 'expense' | null>(null)
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const [selectedMonth, setSelectedMonth] = useState<MonthSelection | null>(null)
  const [selectedSection, setSelectedSection] = useState<ReportSection | null>(null)

  // Year, search and dates live in the link: the card keeps them when the user comes back, and links share them.
  const year = yearFromParam(params.get('y'))
  const search = params.get('q') ?? ''
  const dateFrom = dateFromParam(params.get('from'))
  const dateTo = dateFromParam(params.get('to'))
  // The box keeps its own text: the router applies a new link in a transition, and a box bound to the link would lose keystrokes.
  const [searchText, setSearchText] = useState(search)
  const writtenSearch = useRef(search)

  /** Several keys in one navigation: consecutive setParams calls would each start from the same old query. */
  const patchParams = (patch: Record<string, string | null>) => {
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous)
        for (const [key, value] of Object.entries(patch)) {
          if (value) next.set(key, value)
          else next.delete(key)
        }
        return next
      },
      { replace: true },
    )
  }
  // The current year is the default and stays out of the link.
  const setYear = (value: number | null) =>
    patchParams({ y: value === null || value === currentReportCalendarYear() ? null : String(value) })

  useEffect(() => {
    // A new link from outside (back, forward, another link): the box shows its search.
    if (search === writtenSearch.current) return
    writtenSearch.current = search
    setSearchText(search)
  }, [search])

  useEffect(() => {
    if (searchText === writtenSearch.current) return
    const timer = window.setTimeout(() => {
      writtenSearch.current = searchText
      patchParams({ q: searchText || null })
    }, SEARCH_LINK_DELAY_MS)
    return () => window.clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- a new link restarts the pause, so the write starts from that link
  }, [searchText, params])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setError(null)
      setLoading(true)
      setPayload(null)
      try {
        const data = await LOADERS[report]()
        if (!cancelled) setPayload(data)
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Не удалось загрузить отчёт')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [report, rulesVersion])

  const rows: KeyedReportRow[] = useMemo(
    () => (payload?.rows ?? []).map((row, index) => ({ ...row, rowKey: operationRowKey(row, index) })),
    [payload],
  )
  const matrix = useMemo(() => buildLegacyMatrix(payload, year), [payload, year])
  const effectiveYear = year ?? currentReportCalendarYear()

  const yearSegmentOptions = useMemo(() => {
    const cy = currentReportCalendarYear()
    const merged = new Set<number>([cy, ...matrix.years])
    return Array.from(merged).sort((a, b) => a - b)
  }, [matrix.years])

  const matrixMonthColumnWidthPx = useMemo(
    () => moneyColumnWidthFromMaxChars(maxMatrixMonthMoneyDisplayLen(matrix.rows)),
    [matrix.rows],
  )

  const matrixScrollX = useMemo(() => 340 + 12 * matrixMonthColumnWidthPx, [matrixMonthColumnWidthPx])

  const amountColumnWidthPx = useMemo(
    () => moneyColumnWidthFromMaxChars(maxAmountStringLen(rows)),
    [rows],
  )

  const operationsScrollX = useMemo(
    () => Math.max(1180, 140 + 110 + amountColumnWidthPx + 200 + 200 + 150 + 380 + 360),
    [amountColumnWidthPx],
  )

  useEffect(() => {
    // A year from an old link that has no data falls back to the current year.
    if (year !== null && matrix.years.length > 0 && !matrix.years.includes(year)) setYear(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- setYear only writes the link
  }, [matrix.years, year])

  const filteredRows = useMemo(() => {
    const query = search.trim().toLowerCase()
    const filtered = rows.filter((row) => {
      const dateOnly = String(row.date || '').slice(0, 10)
      if (dateFrom && (!dateOnly || dateOnly < dateFrom)) return false
      if (dateTo && (!dateOnly || dateOnly > dateTo)) return false
      if (selectedDirection && row.direction !== selectedDirection) return false
      if (!rowMatchesSection(row, selectedSection)) return false
      if (selectedCategory) {
        const rowCategory = categoryFromStructuredRow(row)
        if (rowCategory !== selectedCategory) return false
      }
      if (selectedMonth) {
        const ref = parseMonthRef(row.date)
        if (!ref || ref.year !== selectedMonth.year || ref.monthIndex !== selectedMonth.monthIndex) return false
      }
      if (!query) return true
      const hay = `${row.id} ${categoryFromStructuredRow(row)} ${vendorOf(row)} ${row.purpose} ${row.description} ${row.channel}`.toLowerCase()
      return hay.includes(query)
    })
    if (selectedDirection === 'expense') {
      return [...filtered].sort((a, b) => {
        const c = categoryFromStructuredRow(a).localeCompare(categoryFromStructuredRow(b), 'ru', { sensitivity: 'base' })
        if (c !== 0) return c
        return String(b.date || '').localeCompare(String(a.date || ''))
      })
    }
    return filtered
  }, [rows, search, dateFrom, dateTo, selectedDirection, selectedCategory, selectedMonth, selectedSection])

  const rowColumns: ColumnsType<KeyedReportRow> = useMemo(
    () => [
      {
        title: 'Дата',
        dataIndex: 'date',
        width: 140,
        render: (v: string | null) => dateText(v),
        sorter: (a, b) => String(a.date || '').localeCompare(String(b.date || '')),
      },
      {
        title: 'Тип',
        dataIndex: 'direction',
        width: 110,
        render: (v: 'revenue' | 'expense') => (v === 'revenue' ? <Tag color="green">Доход</Tag> : <Tag color="gold">Расход</Tag>),
        filters: [
          { text: 'Доход', value: 'revenue' },
          { text: 'Расход', value: 'expense' },
        ],
        onFilter: (value, record) => record.direction === value,
      },
      {
        title: 'Сумма',
        dataIndex: 'amount',
        width: amountColumnWidthPx,
        align: 'right' as const,
        render: (v: string) => <span style={{ whiteSpace: 'nowrap' }}>{money(v)}</span>,
        sorter: (a, b) => Number(a.amount) - Number(b.amount),
        onHeaderCell: () => ({ style: { whiteSpace: 'nowrap' } }),
        onCell: () => ({ style: { whiteSpace: 'nowrap' } }),
      },
      {
        title: 'Категория',
        dataIndex: 'category',
        width: 160,
        render: (_v: string | undefined, row) => categoryFromStructuredRow(row),
        sorter: (a, b) => categoryFromStructuredRow(a).localeCompare(categoryFromStructuredRow(b)),
      },
      {
        title: 'Поставщик',
        key: 'vendor',
        width: 200,
        ellipsis: true,
        render: (_v: unknown, row) => vendorOf(row) || '—',
        sorter: (a, b) => vendorOf(a).localeCompare(vendorOf(b)),
      },
      { title: 'Канал', dataIndex: 'channel', width: 140, sorter: (a, b) => a.channel.localeCompare(b.channel) },
      { title: 'Назначение', dataIndex: 'purpose', ellipsis: true },
      { title: 'Описание', dataIndex: 'description', ellipsis: true },
    ],
    [amountColumnWidthPx],
  )

  const openFilteredOperations = (filter: OperationsFilter, month?: MonthSelection | null) => {
    setSelectedDirection(filter.direction)
    setSelectedCategory(filter.category)
    setSelectedSection(filter.section)
    setSelectedMonth(month ?? null)
    window.setTimeout(() => {
      operationsCardRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }, 0)
  }

  const matrixColumns: ColumnsType<MatrixRow> = [
    {
      title: String(effectiveYear),
      dataIndex: 'label',
      width: 340,
      fixed: 'left',
      render: (label: string, row) => (row.emphasize ? <Typography.Text strong>{label}</Typography.Text> : label),
    },
    ...matrix.months.map((monthIndex) => ({
      title: MONTH_LABELS[monthIndex],
      key: `m:${monthIndex}`,
      width: matrixMonthColumnWidthPx,
      align: 'right' as const,
      onHeaderCell: () => ({ style: { whiteSpace: 'nowrap' as const } }),
      onCell: () => ({ style: { whiteSpace: 'nowrap' as const } }),
      render: (_: unknown, row: MatrixRow) => {
        if (row.kind === 'section') return ''
        const value = row.values[monthIndex] ?? 0
        if (roundToCents(value) === 0) return <Typography.Text type="secondary">{money(0)}</Typography.Text>
        const text = money(Math.abs(value))
        const clickMonth = { year: effectiveYear, monthIndex }

        const filter = filterForMatrixRow(row) ?? { direction: null, category: null, section: null }
        const content =
          value < 0 ? <Typography.Text type="danger">({text})</Typography.Text> : <Typography.Text>{text}</Typography.Text>
        return (
          <Tooltip title="Нажмите, чтобы посмотреть операции" mouseEnterDelay={0.6}>
            <Button
              type="text"
              size="small"
              onClick={(event) => {
                event.stopPropagation()
                openFilteredOperations(filter, clickMonth)
              }}
              style={{ paddingInline: 6, whiteSpace: 'nowrap', height: 'auto', cursor: 'pointer' }}
            >
              {content}
            </Button>
          </Tooltip>
        )
      },
    })),
  ]

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Card>
        <Space wrap>
          <Input
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            placeholder="Поиск по назначению/каналу/описанию/поставщику"
            allowClear
            style={{ width: 360 }}
          />
          <DatePicker.RangePicker
            value={dateFrom || dateTo ? [dateFrom ? dayjs(dateFrom) : null, dateTo ? dayjs(dateTo) : null] : null}
            onChange={(value) =>
              patchParams({
                from: value?.[0]?.format('YYYY-MM-DD') ?? null,
                to: value?.[1]?.format('YYYY-MM-DD') ?? null,
              })
            }
          />
          <Segmented
            options={yearSegmentOptions.map((y) => ({ label: String(y), value: y }))}
            value={effectiveYear}
            onChange={(v) => setYear(Number(v))}
          />
          {selectedDirection || selectedCategory || selectedMonth || selectedSection ? (
            <Button
              onClick={() => {
                setSelectedDirection(null)
                setSelectedCategory(null)
                setSelectedSection(null)
                setSelectedMonth(null)
              }}
            >
              Сбросить фильтр категории
            </Button>
          ) : null}
        </Space>
      </Card>

      {error ? <Alert type="error" showIcon message={error} /> : null}
      {loading ? <Skeleton active /> : null}

      {!loading && payload ? (
        <>
          {payload.report_settings ? (
            <Card title={`Настройки отчёта (${REPORT_NAMES[report]}, только просмотр)`}>
              <Descriptions bordered size="small" column={1}>
                <Descriptions.Item label="Начало периода (start_month)">
                  {payload.report_settings.start_month ?? '—'}
                </Descriptions.Item>
                <Descriptions.Item label={`Начальный остаток (${REPORT_NAMES[report]})`}>
                  {money(payload.report_settings.opening_balance ?? payload.totals.opening_balance ?? '0')}
                </Descriptions.Item>
                <Descriptions.Item label="Исключения операций кассы">
                  {(payload.report_settings.cash_exclude_operations ?? []).join(', ') || '—'}
                </Descriptions.Item>
                <Descriptions.Item label="Исключения категорий заявок">
                  {(payload.report_settings.request_exclude_categories ?? []).join(', ') || '—'}
                </Descriptions.Item>
                <Descriptions.Item label="Типы оплаты заявок в PnL">
                  {(payload.report_settings.request_payment_types_for_pnl ?? []).join(', ') || '—'}
                </Descriptions.Item>
                <Descriptions.Item label="Назначения: операционные">
                  {(payload.report_settings.payment_purpose_operational ?? []).join(', ') || '—'}
                </Descriptions.Item>
                <Descriptions.Item label="Назначения: прочие">
                  {(payload.report_settings.payment_purpose_other ?? []).join(', ') || '—'}
                </Descriptions.Item>
                <Descriptions.Item label="Назначения: корзина invest_returns">
                  {(payload.report_settings.payment_purpose_invest_returns ?? []).join(', ') || '—'}
                </Descriptions.Item>
                <Descriptions.Item label="Типы выплат → операционные">
                  {(payload.report_settings.invest_return_type_operational ?? []).join(', ') || '—'}
                </Descriptions.Item>
                <Descriptions.Item label="Типы выплат → прочие">
                  {(payload.report_settings.invest_return_type_other ?? []).join(', ') || '—'}
                </Descriptions.Item>
                <Descriptions.Item label="Типы выплат → invest_returns">
                  {(payload.report_settings.invest_return_type_invest_returns ?? []).join(', ') || '—'}
                </Descriptions.Item>
              </Descriptions>
            </Card>
          ) : null}

          <Card
            title={`${REPORT_NAMES[report]}: сводный отчет`}
            extra={payload.metadata.company_name ? <Typography.Text type="secondary">{payload.metadata.company_name}</Typography.Text> : null}
          >
            <Table<MatrixRow>
              rowKey={(r) => r.key}
              columns={matrixColumns}
              dataSource={matrix.rows}
              size="small"
              pagination={false}
              scroll={{ x: matrixScrollX }}
              onRow={(row) => ({
                onClick: () => {
                  const filter = filterForMatrixRow(row)
                  if (filter) openFilteredOperations(filter)
                },
              })}
              rowClassName={(row) => (row.kind === 'revenue' || row.kind === 'expense' || row.kind === 'summary' ? 'clickable-report-row' : '')}
            />
          </Card>

          <div ref={operationsCardRef}>
            <Card
            title={`${REPORT_NAMES[report]}: операции`}
            extra={
              selectedDirection || selectedCategory || selectedMonth || selectedSection ? (
                <Typography.Text type="secondary">
                  Фильтр:{' '}
                  {operationsFilterCaption({
                    direction: selectedDirection,
                    section: selectedSection,
                    category: selectedCategory,
                    month: selectedMonth ? `${MONTH_LABELS[selectedMonth.monthIndex]} ${selectedMonth.year}` : null,
                  })}
                </Typography.Text>
              ) : null
            }
          >
            <Table<KeyedReportRow>
              rowKey={(r) => r.rowKey}
              columns={rowColumns}
              dataSource={filteredRows}
              size="small"
              scroll={{ x: operationsScrollX }}
              pagination={{ pageSize: 50, showSizeChanger: true, pageSizeOptions: [20, 50, 100, 200] }}
              onRow={(row) => {
                const requestId =
                  report === 'pnl' && row.direction === 'expense'
                    ? resolveRequestIdFromPnlExpenseRow(row)
                    : null
                if (!requestId) return {}
                return {
                  onClick: () => navigate(`/requests/${requestId}`),
                  style: { cursor: 'pointer' },
                }
              }}
            />
            </Card>
          </div>
        </>
      ) : null}
    </Space>
  )
}
