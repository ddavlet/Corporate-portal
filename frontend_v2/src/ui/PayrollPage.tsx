import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Collapse,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Select,
  Skeleton,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { Dayjs } from 'dayjs'
import { useNavigate } from 'react-router-dom'
import { getTenantPayrollDocIdFormat, updateTenantPayrollDocIdFormat } from '../lib/api'
import { useInfiniteList } from '../lib/useInfiniteList'
import { ListInfiniteScrollFooter } from './ListInfiniteScrollFooter'
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

function previewPayrollDocId(prefix: string, digitWidth: number, sampleNumeric: number): string {
  const w = Number.isFinite(digitWidth) ? Math.min(32, Math.max(1, Math.floor(digitWidth))) : 9
  const core = String(Math.trunc(sampleNumeric)).padStart(w, '0')
  return `${prefix}${core}`
}

function PayrollDocIdFormatSection() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [hidden, setHidden] = useState(false)
  const [form] = Form.useForm<{
    payroll_doc_id_prefix: string
    payroll_doc_id_digit_width: number
  }>()
  const prefixWatch = Form.useWatch('payroll_doc_id_prefix', form)
  const widthWatch = Form.useWatch('payroll_doc_id_digit_width', form)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        const data = await getTenantPayrollDocIdFormat()
        if (cancelled) return
        form.setFieldsValue({
          payroll_doc_id_prefix: data.payroll_doc_id_prefix ?? '',
          payroll_doc_id_digit_width: data.payroll_doc_id_digit_width ?? 9,
        })
        setHidden(false)
      } catch {
        if (!cancelled) setHidden(true)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [form])

  if (hidden) return null

  const p = typeof prefixWatch === 'string' ? prefixWatch : ''
  const dw = typeof widthWatch === 'number' ? widthWatch : 9
  const preview = previewPayrollDocId(p, dw, 459)

  const onSave = async () => {
    try {
      const v = await form.validateFields()
      setSaving(true)
      await updateTenantPayrollDocIdFormat({
        payroll_doc_id_prefix: v.payroll_doc_id_prefix.trim(),
        payroll_doc_id_digit_width: v.payroll_doc_id_digit_width,
      })
      message.success('Сохранено')
    } catch (e: unknown) {
      if (e && typeof e === 'object' && 'errorFields' in e) return
      message.error(e instanceof Error ? e.message : 'Ошибка сохранения')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card title="Формат номера ведомости (doc_id)" style={{ marginBottom: 16 }} loading={loading}>
      <Typography.Paragraph type="secondary">
        Привязка заявки типа «Начисление ЗП»: можно ввести короткий номер (например{' '}
        <Typography.Text code>459</Typography.Text>), система найдёт документ по полному <Typography.Text code>doc_id</Typography.Text>.
      </Typography.Paragraph>
      <Form form={form} layout="vertical" disabled={loading}>
        <Form.Item
          label="Префикс перед номером"
          name="payroll_doc_id_prefix"
          rules={[{ max: 32, message: 'Не длиннее 32 символов' }]}
        >
          <Input placeholder="Например: 1- или пусто" allowClear />
        </Form.Item>
        <Form.Item
          label="Числовая часть: знаков всего"
          name="payroll_doc_id_digit_width"
          rules={[{ required: true }]}
        >
          <InputNumber min={1} max={32} style={{ width: '100%' }} />
        </Form.Item>
      </Form>
      <Typography.Paragraph style={{ marginBottom: 16 }}>
        Пример: ввод <Typography.Text code>459</Typography.Text> совпадает с ведомостью{' '}
        <Typography.Text code>{preview}</Typography.Text>.
      </Typography.Paragraph>
      <Button type="primary" onClick={() => void onSave()} loading={saving} disabled={loading}>
        Сохранить формат
      </Button>
    </Card>
  )
}

export function PayrollPage() {
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [docIdFilter, setDocIdFilter] = useState('')
  const [employeeSearch, setEmployeeSearch] = useState('')
  const [periodRange, setPeriodRange] = useState<[Dayjs | null, Dayjs | null] | null>(null)
  const [createdRange, setCreatedRange] = useState<[Dayjs | null, Dayjs | null] | null>(null)
  const [amountMin, setAmountMin] = useState<number | null>(null)
  const [amountMax, setAmountMax] = useState<number | null>(null)
  const [requestFilter, setRequestFilter] = useState<string | undefined>(undefined)

  const listUrl = useMemo(() => {
    const params = new URLSearchParams()
    if (docIdFilter.trim()) params.set('doc_id', docIdFilter.trim())
    if (employeeSearch.trim()) params.set('employee_search', employeeSearch.trim())
    const periodFrom = periodRange?.[0]?.format('YYYY-MM-DD')
    const periodTo = periodRange?.[1]?.format('YYYY-MM-DD')
    if (periodFrom) params.set('period_from', periodFrom)
    if (periodTo) params.set('period_to', periodTo)
    const createdFrom = createdRange?.[0]?.format('YYYY-MM-DD')
    const createdTo = createdRange?.[1]?.format('YYYY-MM-DD')
    if (createdFrom) params.set('created_from', createdFrom)
    if (createdTo) params.set('created_to', createdTo)
    if (amountMin !== null) params.set('amount_min', String(amountMin))
    if (amountMax !== null) params.set('amount_max', String(amountMax))
    if (search.trim()) params.set('search', search.trim())
    if (requestFilter === 'with_request') params.set('has_request', '1')
    if (requestFilter === 'without_request') params.set('has_request', '0')
    if (requestFilter === 'unpaid') params.set('missing_request', '1')
    const q = params.toString()
    return q ? `/api/payroll/documents/?${q}` : '/api/payroll/documents/'
  }, [docIdFilter, employeeSearch, periodRange, createdRange, amountMin, amountMax, search, requestFilter])

  const {
    items: rows,
    loading,
    error,
    hasMore,
    loadingMore,
    sentinelRef,
  } = useInfiniteList<PayrollDocumentRow>({ url: listUrl })

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
    <>
      <PayrollDocIdFormatSection />
      <Card>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Начисления ЗП
      </Typography.Title>
      <Typography.Paragraph type="secondary">
        Документы начислений по <span className="mono">doc_id</span>; заявки с типом оплаты «Начисление ЗП» привязываются к
        документу по <span className="mono">expense_id</span>.
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
        <>
          <Table<PayrollDocumentRow>
            rowKey="id"
            columns={columns}
            dataSource={rows}
            pagination={false}
          />
          <ListInfiniteScrollFooter
            sentinelRef={sentinelRef}
            hasMore={hasMore}
            loadingMore={loadingMore}
            visibleCount={rows.length}
          />
        </>
      ) : null}
    </Card>
    </>
  )
}
