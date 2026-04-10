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

const moneyFmt = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })
const REPORT_TZ = 'Asia/Tashkent'
const MONTH_LABELS = ['Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн', 'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек']

function money(value: string | number): string {
  const n = typeof value === 'number' ? value : Number(String(value).replace(',', '.'))
  return Number.isFinite(n) ? moneyFmt.format(n) : '0'
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

type MatrixRow = {
  key: string
  label: string
  kind: 'section' | 'revenue' | 'expense' | 'summary'
  values: number[]
  emphasize?: boolean
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
  for (const row of [...(report.revenue ?? []), ...(report.expense ?? [])]) {
    const ref = parseMonthRef(row.date)
    if (ref) yearsSet.add(ref.year)
  }
  const years = Array.from(yearsSet).sort((a, b) => a - b)
  const effectiveYear = year ?? years[years.length - 1] ?? new Date().getFullYear()
  const months = Array.from({ length: 12 }, (_, i) => i)

  const revByCat = new Map<string, number[]>()
  const expByCat = new Map<string, number[]>()
  const revTotals = Array(12).fill(0) as number[]
  const expTotals = Array(12).fill(0) as number[]

  for (const row of report.revenue ?? []) {
    const ref = parseMonthRef(row.date)
    if (!ref || ref.year !== effectiveYear) continue
    const amount = Math.abs(parseAmount(row.amount ?? row.kredit))
    const category = categoryFromItem(row)
    const bucket = revByCat.get(category) ?? Array(12).fill(0)
    bucket[ref.monthIndex] += amount
    revTotals[ref.monthIndex] += amount
    revByCat.set(category, bucket)
  }

  for (const row of report.expense ?? []) {
    const ref = parseMonthRef(row.date)
    if (!ref || ref.year !== effectiveYear) continue
    const amount = Math.abs(parseAmount(row.amount ?? row.kredit))
    const category = categoryFromItem(row)
    const bucket = expByCat.get(category) ?? Array(12).fill(0)
    bucket[ref.monthIndex] -= amount
    expTotals[ref.monthIndex] -= amount
    expByCat.set(category, bucket)
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

  const expenseRows: MatrixRow[] = Array.from(expByCat.entries())
    .sort(sortCategoryAz)
    .map(([label, values]) => ({ key: `exp:${label}`, label, kind: 'expense', values }))

  const net = revTotals.map((v, idx) => v + expTotals[idx])
  const cumulative = net.reduce((acc: number[], current, idx) => {
    acc[idx] = (acc[idx - 1] ?? 0) + current
    return acc
  }, Array(12).fill(0))

  const rows: MatrixRow[] = [
    { key: 'section:income', label: 'Доходы', kind: 'section', values: Array(12).fill(0), emphasize: true },
    ...revenueRows,
    { key: 'sum:income', label: 'Итого доходы', kind: 'summary', values: revTotals, emphasize: true },
    { key: 'section:expense', label: 'Расходы', kind: 'section', values: Array(12).fill(0), emphasize: true },
    ...expenseRows,
    { key: 'sum:expense', label: 'Итого расходы', kind: 'summary', values: expTotals, emphasize: true },
    { key: 'sum:net', label: 'Чистая прибыль', kind: 'summary', values: net, emphasize: true },
    { key: 'sum:cumulative', label: 'Суммарная прибыль (с стартового месяца)', kind: 'summary', values: cumulative, emphasize: true },
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
  const effectiveYear = year ?? matrix.years[matrix.years.length - 1] ?? new Date().getFullYear()

  useEffect(() => {
    if (!matrix.years.length) return
    if (year && matrix.years.includes(year)) return
    setYear(matrix.years[matrix.years.length - 1] ?? null)
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

  const rowColumns: ColumnsType<StructuredReportRow> = [
    { title: 'Дата', dataIndex: 'date', width: 140, render: (v: string | null) => dateText(v), sorter: (a, b) => String(a.date || '').localeCompare(String(b.date || '')) },
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
    { title: 'Сумма', dataIndex: 'amount', width: 150, align: 'right', render: (v: string) => money(v), sorter: (a, b) => Number(a.amount) - Number(b.amount) },
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
  ]

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
      width: 120,
      align: 'right' as const,
      render: (_: unknown, row: MatrixRow) => {
        if (row.kind === 'section') return ''
        const value = row.values[monthIndex] ?? 0
        if (Math.abs(value) < 0.000001) return <Typography.Text type="secondary">0.0</Typography.Text>
        const text = money(Math.abs(value))
        const clickMonth = { year: effectiveYear, monthIndex }

        const resolveCellFilter = (): { direction: 'revenue' | 'expense' | null; category: string | null } => {
          if (row.kind === 'revenue') return { direction: 'revenue', category: row.label }
          if (row.kind === 'expense') return { direction: 'expense', category: row.label }
          if (row.key === 'sum:income') return { direction: 'revenue', category: null }
          if (row.key === 'sum:expense') return { direction: 'expense', category: null }
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
            style={{ paddingInline: 4, minWidth: 0 }}
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
            options={(matrix.years.length ? matrix.years : [effectiveYear]).map((y) => ({ label: String(y), value: y }))}
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
              scroll={{ x: 1500 }}
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
                  if (row.kind === 'section' && row.label === 'Расходы') {
                    openFilteredOperations('expense', null)
                    return
                  }
                  if (row.key === 'sum:income') {
                    openFilteredOperations('revenue', null)
                    return
                  }
                  if (row.key === 'sum:expense') {
                    openFilteredOperations('expense', null)
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
              scroll={{ x: 1200 }}
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
