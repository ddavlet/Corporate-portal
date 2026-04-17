import { useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Card, DatePicker, Input, Segmented, Skeleton, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { Dayjs } from 'dayjs'
import { useNavigate } from 'react-router-dom'
import {
  getStructuredCashflowReport,
  getStructuredPnlReport,
  type LegacyReportItem,
  type StructuredReportPayload,
  type StructuredReportRow,
} from '../lib/api'

type ReportKind = 'pnl' | 'cashflow'

type MatrixRow = {
  key: string
  label: string
  kind: 'section' | 'revenue' | 'expense' | 'summary'
  values: number[]
  emphasize?: boolean
}

const moneyFmt = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const REPORT_TZ = 'Asia/Tashkent'
const MONTH_LABELS = ['Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн', 'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек']

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
  const balance = net.map((v, idx) => roundToCents(v + investReturnsTotals[idx]))
  const cumulative = balance.reduce((acc: number[], current, idx) => {
    acc[idx] = roundToCents((acc[idx - 1] ?? 0) + current)
    return acc
  }, Array(12).fill(0))

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
    { key: 'sum:cumulative', label: 'Суммарный остаток (с стартового месяца)', kind: 'summary', values: cumulative, emphasize: true },
  ]

  return { months, rows, years }
}

export function ReportsPage() {
  const navigate = useNavigate()
  const operationsCardRef = useRef<HTMLDivElement | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [active, setActive] = useState<ReportKind>('pnl')
  const [pnl, setPnl] = useState<StructuredReportPayload | null>(null)
  const [cashflow, setCashflow] = useState<StructuredReportPayload | null>(null)
  const [search, setSearch] = useState('')
  const [range, setRange] = useState<[Dayjs | null, Dayjs | null] | null>(null)
  const [year, setYear] = useState<number | null>(null)
  const [selectedDirection, setSelectedDirection] = useState<'revenue' | 'expense' | null>(null)
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const [selectedMonth, setSelectedMonth] = useState<MonthSelection | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setError(null)
      setLoading(true)
      try {
        const [pnlData, cashflowData] = await Promise.all([getStructuredPnlReport(), getStructuredCashflowReport()])
        if (cancelled) return
        setPnl(pnlData)
        setCashflow(cashflowData)
      } catch (e: unknown) {
        if (cancelled) return
        setError(e instanceof Error ? e.message : 'Не удалось загрузить отчеты')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const report = active === 'pnl' ? pnl : cashflow
  const rows = report?.rows ?? []
  const matrix = useMemo(() => buildLegacyMatrix(report, year), [report, year])
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
    () => Math.max(1180, 140 + 110 + amountColumnWidthPx + 200 + 150 + 380 + 360),
    [amountColumnWidthPx],
  )

  useEffect(() => {
    const cy = currentReportCalendarYear()
    if (year === null) {
      setYear(cy)
      return
    }
    if (matrix.years.length > 0 && !matrix.years.includes(year)) {
      setYear(cy)
    }
  }, [matrix.years, year])

  const filteredRows = useMemo(() => {
    const query = search.trim().toLowerCase()
    const from = range?.[0]?.format('YYYY-MM-DD')
    const to = range?.[1]?.format('YYYY-MM-DD')
    const filtered = rows.filter((row) => {
      const dateOnly = String(row.date || '').slice(0, 10)
      if (from && (!dateOnly || dateOnly < from)) return false
      if (to && (!dateOnly || dateOnly > to)) return false
      if (selectedDirection && row.direction !== selectedDirection) return false
      if (selectedCategory) {
        const rowCategory = categoryFromStructuredRow(row)
        if (rowCategory !== selectedCategory) return false
      }
      if (selectedMonth) {
        const ref = parseMonthRef(row.date)
        if (!ref || ref.year !== selectedMonth.year || ref.monthIndex !== selectedMonth.monthIndex) return false
      }
      if (!query) return true
      const hay = `${row.id} ${categoryFromStructuredRow(row)} ${row.purpose} ${row.description} ${row.channel}`.toLowerCase()
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
  }, [rows, search, range, selectedDirection, selectedCategory, selectedMonth])

  const rowColumns: ColumnsType<StructuredReportRow> = useMemo(
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
      { title: 'Канал', dataIndex: 'channel', width: 140, sorter: (a, b) => a.channel.localeCompare(b.channel) },
      { title: 'Назначение', dataIndex: 'purpose', ellipsis: true },
      { title: 'Описание', dataIndex: 'description', ellipsis: true },
    ],
    [amountColumnWidthPx],
  )

  const openFilteredOperations = (
    direction: 'revenue' | 'expense' | null,
    category: string | null,
    month?: MonthSelection | null,
  ) => {
    setSelectedDirection(direction)
    setSelectedCategory(category)
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

        const resolveCellFilter = (): { direction: 'revenue' | 'expense' | null; category: string | null } => {
          if (row.kind === 'revenue') return { direction: 'revenue', category: row.label }
          if (row.kind === 'expense') return { direction: 'expense', category: row.label }
          if (row.key === 'sum:income') return { direction: 'revenue', category: null }
          if (row.key === 'sum:operational-expense') return { direction: 'expense', category: null }
          if (row.key === 'sum:other-expense') return { direction: 'expense', category: null }
          if (row.key === 'sum:invest_returns') return { direction: null, category: 'Выплаты по инвестициям' }
          return { direction: null, category: null }
        }

        const { direction, category } = resolveCellFilter()
        const content =
          value < 0 ? <Typography.Text type="danger">({text})</Typography.Text> : <Typography.Text>{text}</Typography.Text>
        return (
          <Button
            type="text"
            size="small"
            onClick={(event) => {
              event.stopPropagation()
              openFilteredOperations(direction, category, clickMonth)
            }}
            style={{ paddingInline: 6, whiteSpace: 'nowrap', height: 'auto' }}
          >
            {content}
          </Button>
        )
      },
    })),
  ]

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Card>
        <Typography.Title level={4} style={{ marginTop: 0 }}>
          Отчеты
        </Typography.Title>
        <Space wrap>
          <Segmented
            options={[
              { label: 'PnL', value: 'pnl' },
              { label: 'Cashflow', value: 'cashflow' },
            ]}
            value={active}
            onChange={(v) => setActive(v as ReportKind)}
          />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Поиск по назначению/каналу/описанию"
            allowClear
            style={{ width: 360 }}
          />
          <DatePicker.RangePicker value={range} onChange={(v) => setRange(v as [Dayjs | null, Dayjs | null])} />
          <Segmented
            options={yearSegmentOptions.map((y) => ({ label: String(y), value: y }))}
            value={effectiveYear}
            onChange={(v) => setYear(Number(v))}
          />
          {selectedDirection || selectedCategory || selectedMonth ? (
            <Button
              onClick={() => {
                setSelectedDirection(null)
                setSelectedCategory(null)
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

      {!loading && report ? (
        <>
          <Card
            title={`${active === 'pnl' ? 'PnL' : 'Cashflow'}: сводный отчет`}
            extra={report.metadata.company_name ? <Typography.Text type="secondary">{report.metadata.company_name}</Typography.Text> : null}
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
                  if (row.kind === 'revenue' || row.kind === 'expense') {
                    openFilteredOperations(row.kind, row.label)
                    return
                  }
                  if (row.kind === 'section' && row.label === 'Доходы') {
                    openFilteredOperations('revenue', null)
                    return
                  }
                  if (row.kind === 'section' && row.label === 'Операционные расходы') {
                    openFilteredOperations('expense', null)
                    return
                  }
                  if (row.kind === 'section' && row.label === 'Прочие расходы') {
                    openFilteredOperations('expense', null)
                    return
                  }
                  if (row.key === 'sum:income') {
                    openFilteredOperations('revenue', null)
                    return
                  }
                  if (row.key === 'sum:operational-expense') {
                    openFilteredOperations('expense', null)
                    return
                  }
                  if (row.key === 'sum:other-expense') {
                    openFilteredOperations('expense', null)
                    return
                  }
                  if (row.key === 'sum:invest_returns') {
                    openFilteredOperations(null, 'Выплаты по инвестициям')
                    return
                  }
                },
              })}
              rowClassName={(row) => (row.kind === 'revenue' || row.kind === 'expense' || row.kind === 'summary' ? 'clickable-report-row' : '')}
            />
          </Card>

          <div ref={operationsCardRef}>
            <Card
            title={`${active === 'pnl' ? 'PnL' : 'Cashflow'}: операции`}
            extra={
              selectedDirection || selectedCategory || selectedMonth ? (
                <Typography.Text type="secondary">
                  Фильтр: {selectedDirection === 'revenue' ? 'Доход' : selectedDirection === 'expense' ? 'Расход' : 'Все'}
                  {selectedCategory ? ` / ${selectedCategory}` : ''}
                  {selectedMonth ? ` / ${MONTH_LABELS[selectedMonth.monthIndex]} ${selectedMonth.year}` : ''}
                </Typography.Text>
              ) : null
            }
          >
            <Table<StructuredReportRow>
              rowKey={(r) => `${r.direction}:${r.id}:${r.date ?? ''}`}
              columns={rowColumns}
              dataSource={filteredRows}
              size="small"
              scroll={{ x: operationsScrollX }}
              pagination={{ pageSize: 50, showSizeChanger: true, pageSizeOptions: [20, 50, 100, 200] }}
              onRow={(row) => {
                const requestId =
                  active === 'pnl' && row.direction === 'expense'
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
