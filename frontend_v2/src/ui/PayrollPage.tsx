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
  Modal,
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
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import {
  createPayrollDocument,
  type PayrollLineCreatePayload,
} from '../lib/api'
import { useInfiniteList } from '../lib/useInfiniteList'
import { ListInfiniteScrollFooter } from './ListInfiniteScrollFooter'
import { labelBlockAboveField } from './formSpacing'

type PayrollDocumentRow = {
  id: number
  doc_id: string | null
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

type CreatePayrollLineFormValue = {
  employee: string
  item: string
  description?: string
  sum: number
  days_plan?: number | null
  days_fact?: number | null
  period?: [Dayjs, Dayjs] | null
}

function CreatePayrollDocumentModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean
  onClose: () => void
  onCreated: () => void
}) {
  const [form] = Form.useForm<{ lines: CreatePayrollLineFormValue[] }>()
  const [saving, setSaving] = useState(false)

  const onSubmit = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      const lines: PayrollLineCreatePayload[] = values.lines.map((line) => ({
        employee: line.employee,
        item: line.item,
        description: line.description,
        sum: line.sum,
        days_plan: line.days_plan ?? null,
        days_fact: line.days_fact ?? null,
        period_start: line.period?.[0]?.format('YYYY-MM-DD') ?? null,
        period_end: line.period?.[1]?.format('YYYY-MM-DD') ?? null,
      }))
      await createPayrollDocument({ lines })
      message.success('Начисление создано')
      form.resetFields()
      onCreated()
      onClose()
    } catch (e: unknown) {
      if (e && typeof e === 'object' && 'errorFields' in e) return
      message.error(e instanceof Error ? e.message : 'Ошибка создания')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title="Создать начисление"
      open={open}
      onCancel={onClose}
      onOk={() => void onSubmit()}
      confirmLoading={saving}
      width={900}
      okText="Создать"
      destroyOnClose
    >
      <Form form={form} layout="vertical" initialValues={{ lines: [{}] }}>
        <Form.List name="lines">
          {(fields, { add, remove }) => (
            <Space direction="vertical" style={{ display: 'flex' }} size={12}>
              {fields.map((field) => (
                <Space key={field.key} align="baseline" wrap>
                  <Form.Item
                    {...field}
                    name={[field.name, 'employee']}
                    rules={[{ required: true, message: 'ФИО обязательно' }]}
                  >
                    <Input placeholder="Сотрудник (ФИО)" style={{ width: 200 }} />
                  </Form.Item>
                  <Form.Item
                    {...field}
                    name={[field.name, 'item']}
                    rules={[{ required: true, message: 'Вид начисления обязателен' }]}
                  >
                    <Input placeholder="Вид (Salary / Bonus…)" style={{ width: 160 }} />
                  </Form.Item>
                  <Form.Item {...field} name={[field.name, 'description']}>
                    <Input placeholder="Описание" style={{ width: 160 }} />
                  </Form.Item>
                  <Form.Item
                    {...field}
                    name={[field.name, 'sum']}
                    rules={[{ required: true, message: 'Сумма обязательна' }]}
                  >
                    <InputNumber placeholder="Сумма" min={0} style={{ width: 130 }} />
                  </Form.Item>
                  <Form.Item {...field} name={[field.name, 'days_plan']}>
                    <InputNumber placeholder="Дни план" min={0} style={{ width: 100 }} />
                  </Form.Item>
                  <Form.Item {...field} name={[field.name, 'days_fact']}>
                    <InputNumber placeholder="Дни факт" min={0} style={{ width: 100 }} />
                  </Form.Item>
                  <Form.Item {...field} name={[field.name, 'period']}>
                    <DatePicker.RangePicker placeholder={['Период от', 'Период до']} />
                  </Form.Item>
                  {fields.length > 1 ? (
                    <Button icon={<DeleteOutlined />} onClick={() => remove(field.name)} />
                  ) : null}
                </Space>
              ))}
              <Button type="dashed" icon={<PlusOutlined />} onClick={() => add()}>
                Добавить строку
              </Button>
            </Space>
          )}
        </Form.List>
      </Form>
    </Modal>
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
  const [createModalOpen, setCreateModalOpen] = useState(false)

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
    reload,
  } = useInfiniteList<PayrollDocumentRow>({ url: listUrl })

  const columns: ColumnsType<PayrollDocumentRow> = useMemo(
    () => [
      {
        title: 'Документ (doc_id)',
        dataIndex: 'doc_id',
        key: 'doc_id',
        sorter: (a, b) => String(a.doc_id || '').localeCompare(String(b.doc_id || '')),
        render: (v: string | null, r) => (
          <Button type="link" onClick={() => navigate(`/payroll/${r.id}`)} style={{ padding: 0 }}>
            {v || 'Без номера (создано в портале)'}
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
      <Card>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Начисления ЗП
      </Typography.Title>
      <Button type="primary" onClick={() => setCreateModalOpen(true)} style={{ marginBottom: 16 }}>
        Создать начисление
      </Button>
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
      <CreatePayrollDocumentModal
        open={createModalOpen}
        onClose={() => setCreateModalOpen(false)}
        onCreated={() => void reload()}
      />
    </Card>
    </>
  )
}
