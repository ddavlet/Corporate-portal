import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Collapse,
  DatePicker,
  Input,
  InputNumber,
  Select,
  Skeleton,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { Dayjs } from 'dayjs'
import { useNavigate } from 'react-router-dom'
import { apiFetch } from '../lib/api'
import { labelBlockAboveField } from './formSpacing'

type PayrollDocumentRow = {
  id: number
  doc_id: string
  created_at: string
  total_sum: string | number
  lines_count: number
  has_request?: boolean
  has_paid_request?: boolean
  matched_request_id?: number | null
}

const dateFormatterTashkent = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  timeZone: 'Asia/Tashkent',
})

function formatDate(value?: string | null): string {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '-'
  return dateFormatterTashkent.format(parsed)
}

function compareDateStrings(a?: string | null, b?: string | null): number {
  return String(a || '').localeCompare(String(b || ''))
}

function normalizeRows(payload: unknown): PayrollDocumentRow[] {
  if (Array.isArray(payload)) return payload as PayrollDocumentRow[]
  if (payload && typeof payload === 'object' && 'results' in payload) {
    const results = (payload as { results?: unknown }).results
    return Array.isArray(results) ? (results as PayrollDocumentRow[]) : []
  }
  return []
}

export function PayrollPage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [rows, setRows] = useState<PayrollDocumentRow[]>([])
  const [search, setSearch] = useState('')
  const [docIdFilter, setDocIdFilter] = useState('')
  const [employeeSearch, setEmployeeSearch] = useState('')
  const [periodRange, setPeriodRange] = useState<[Dayjs | null, Dayjs | null] | null>(null)
  const [createdRange, setCreatedRange] = useState<[Dayjs | null, Dayjs | null] | null>(null)
  const [amountMin, setAmountMin] = useState<number | null>(null)
  const [amountMax, setAmountMax] = useState<number | null>(null)
  const [requestFilter, setRequestFilter] = useState<string | undefined>(undefined)
  const [currentPage, setCurrentPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setError(null)
      try {
        const params = new URLSearchParams()
        if (docIdFilter.trim()) params.set('doc_id', docIdFilter.trim())
        if (employeeSearch.trim()) params.set('employee_search', employeeSearch.trim())
        const periodFrom = periodRange?.[0]?.format('YYYY-MM-DD')
        const periodTo = periodRange?.[1]?.format('YYYY-MM-DD')
        if (periodFrom) params.set('period_from', periodFrom)
        if (periodTo) params.set('period_to', periodTo)
        const q = params.toString()
        const res = await apiFetch(q ? `/api/payroll/documents/?${q}` : '/api/payroll/documents/')
        const json = await res.json().catch(() => null)
        if (!res.ok) {
          throw new Error(typeof json === 'object' && json ? JSON.stringify(json) : `HTTP ${res.status}`)
        }
        if (!cancelled) setRows(normalizeRows(json))
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Ошибка загрузки')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [docIdFilter, employeeSearch, periodRange])

  const filteredRows = useMemo(() => {
    const normalized = search.trim().toLowerCase()
    const createdFrom = createdRange?.[0]?.format('YYYY-MM-DD')
    const createdTo = createdRange?.[1]?.format('YYYY-MM-DD')

    return rows.filter((row) => {
      const amountNum = Number(row.total_sum)
      if (amountMin !== null && amountNum < amountMin) return false
      if (amountMax !== null && amountNum > amountMax) return false

      const createdDate = String(row.created_at || '').slice(0, 10)
      if (createdFrom && (!createdDate || createdDate < createdFrom)) return false
      if (createdTo && (!createdDate || createdDate > createdTo)) return false

      if (requestFilter === 'with_request' && !row.has_request) return false
      if (requestFilter === 'without_request' && row.has_request) return false
      if (requestFilter === 'paid' && !row.has_paid_request) return false
      if (requestFilter === 'unpaid' && row.has_paid_request) return false

      if (!normalized) return true
      const haystack = JSON.stringify(row).toLowerCase()
      return haystack.includes(normalized)
    })
  }, [rows, search, createdRange, amountMin, amountMax, requestFilter])

  useEffect(() => {
    setCurrentPage(1)
  }, [search, createdRange, amountMin, amountMax, requestFilter, docIdFilter, employeeSearch, periodRange])

  const columns: ColumnsType<PayrollDocumentRow> = useMemo(
    () => [
      {
        title: 'Документ (doc_id)',
        dataIndex: 'doc_id',
        key: 'doc_id',
        sorter: (a, b) => String(a.doc_id || '').localeCompare(String(b.doc_id || '')),
        render: (v: string, r) => (
          <Button type="link" onClick={() => navigate(`/payroll/${r.id}`)} style={{ padding: 0 }}>
            {v}
          </Button>
        ),
      },
      {
        title: 'Дата создания',
        dataIndex: 'created_at',
        key: 'created_at',
        width: 160,
        sorter: (a, b) => compareDateStrings(a.created_at, b.created_at),
        render: (v: string) => formatDate(v),
      },
      {
        title: <Tooltip title="Число позиций в документе">Кол-во строк</Tooltip>,
        dataIndex: 'lines_count',
        key: 'lines_count',
        width: 110,
        sorter: (a, b) => a.lines_count - b.lines_count,
      },
      {
        title: 'Сумма',
        dataIndex: 'total_sum',
        key: 'total_sum',
        width: 140,
        sorter: (a, b) => Number(a.total_sum) - Number(b.total_sum),
        render: (v: string | number) =>
          Number(v).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
      },
      {
        title: 'Заявка',
        key: 'req',
        width: 200,
        render: (_, r) => (
          <Space size={4} wrap>
            {r.has_request ? <Tag color="blue">Есть заявка</Tag> : null}
            {r.has_paid_request ? <Tag color="green">Оплачено</Tag> : null}
            {r.matched_request_id ? (
              <Button type="link" size="small" onClick={() => navigate(`/requests/${r.matched_request_id}`)}>
                №{r.matched_request_id}
              </Button>
            ) : null}
          </Space>
        ),
      },
    ],
    [navigate],
  )

  const activeAdvancedFilters = [
    docIdFilter.trim(),
    employeeSearch.trim(),
    periodRange,
    createdRange,
    amountMin,
    amountMax,
    requestFilter,
  ].filter(Boolean).length

  return (
    <Card>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Начисления ЗП
      </Typography.Title>
      <Typography.Paragraph type="secondary">
        Документы начислений по <span className="mono">doc_id</span>; заявки (наличные, категория зарплаты) привязываются к
        документу.
      </Typography.Paragraph>
      <div style={{ marginBottom: 16 }}>
        <Typography.Text type="secondary" style={labelBlockAboveField}>
          Поиск
        </Typography.Text>
        <Input
          allowClear
          placeholder="Поиск по doc_id, сумме, заявке…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ width: 320 }}
        />
        <Collapse
          size="small"
          style={{ marginTop: 8 }}
          items={[
            {
              key: 'filters',
              label:
                activeAdvancedFilters > 0
                  ? `Расширенные фильтры (${activeAdvancedFilters} активно)`
                  : 'Расширенные фильтры',
              children: (
                <Space wrap size={[12, 12]} align="end">
                  <div>
                    <Typography.Text style={labelBlockAboveField}>doc_id</Typography.Text>
                    <Input
                      allowClear
                      placeholder="doc_id"
                      value={docIdFilter}
                      onChange={(e) => setDocIdFilter(e.target.value)}
                      style={{ width: 200 }}
                    />
                  </div>
                  <div>
                    <Typography.Text style={labelBlockAboveField}>Сотрудник</Typography.Text>
                    <Input
                      allowClear
                      placeholder="поиск по ФИО"
                      value={employeeSearch}
                      onChange={(e) => setEmployeeSearch(e.target.value)}
                      style={{ width: 200 }}
                    />
                  </div>
                  <div>
                    <Typography.Text style={labelBlockAboveField}>Период начисления</Typography.Text>
                    <DatePicker.RangePicker
                      value={periodRange}
                      onChange={(v) => setPeriodRange(v)}
                      placeholder={['Период от', 'Период до']}
                    />
                  </div>
                  <div>
                    <Typography.Text style={labelBlockAboveField}>Дата создания</Typography.Text>
                    <DatePicker.RangePicker
                      value={createdRange}
                      onChange={(v) => setCreatedRange(v)}
                      placeholder={['Создан от', 'Создан до']}
                    />
                  </div>
                  <InputNumber placeholder="Мин. сумма" min={0} value={amountMin} onChange={setAmountMin} />
                  <InputNumber placeholder="Макс. сумма" min={0} value={amountMax} onChange={setAmountMax} />
                  <Select
                    placeholder="Заявка"
                    allowClear
                    style={{ width: 200 }}
                    value={requestFilter}
                    onChange={setRequestFilter}
                    options={[
                      { value: 'with_request', label: 'Есть заявка' },
                      { value: 'without_request', label: 'Без заявки' },
                      { value: 'paid', label: 'Оплачено' },
                      { value: 'unpaid', label: 'Не оплачено' },
                    ]}
                  />
                  <Button
                    onClick={() => {
                      setDocIdFilter('')
                      setEmployeeSearch('')
                      setPeriodRange(null)
                      setCreatedRange(null)
                      setAmountMin(null)
                      setAmountMax(null)
                      setRequestFilter(undefined)
                    }}
                  >
                    Сбросить фильтры
                  </Button>
                </Space>
              ),
            },
          ]}
        />
      </div>
      {loading ? <Skeleton active /> : null}
      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} /> : null}
      {!loading && !error ? (
        <Table<PayrollDocumentRow>
          rowKey="id"
          columns={columns}
          dataSource={filteredRows}
          pagination={{
            current: currentPage,
            pageSize,
            showSizeChanger: true,
            pageSizeOptions: [20, 50, 100, 200],
            onChange: (page, size) => {
              setCurrentPage(page)
              if (size) setPageSize(size)
            },
          }}
        />
      ) : null}
    </Card>
  )
}
