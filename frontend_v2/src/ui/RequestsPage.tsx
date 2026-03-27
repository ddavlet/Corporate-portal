import { useEffect, useMemo, useState } from 'react'
import { Alert, Card, DatePicker, Descriptions, Divider, Input, InputNumber, Modal, Select, Skeleton, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType, TableProps } from 'antd/es/table'
import type { Dayjs } from 'dayjs'
import { apiFetch } from '../lib/api'

type RequestRow = {
  id: number
  title: string
  description: string
  amount: number
  currency: string
  status: string
  urgency: string
  payment_type: string
  category: string
  vendor: string
  payment_purpose?: string
  file_link?: string | null
  requester: number | null
  requester_username?: string | null
  submitted_at: string
  billing_date: string
}

type ApprovalItem = {
  id: number
  step: number
  step_type: string
  decision: string
  comment?: string | null
  decided_at?: string | null
  approver_username?: string | null
}

type RequestDetail = RequestRow & {
  approvals: ApprovalItem[]
}

type SortState = {
  field: keyof RequestRow | null
  order: 'ascend' | 'descend' | null
}

function normalizeRows(payload: unknown): RequestRow[] {
  if (Array.isArray(payload)) return payload as RequestRow[]
  if (payload && typeof payload === 'object' && 'results' in payload) {
    const results = (payload as { results?: unknown }).results
    return Array.isArray(results) ? (results as RequestRow[]) : []
  }
  return []
}

const dateFormatterTashkent = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  timeZone: 'Asia/Tashkent',
})

function formatDateDDMMYYYY(value?: string | null): string {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '-'
  return dateFormatterTashkent.format(parsed)
}

export function RequestsPage() {
  const [loading, setLoading] = useState(true)
  const [rows, setRows] = useState<RequestRow[]>([])
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [status, setStatus] = useState<string | undefined>(undefined)
  const [urgency, setUrgency] = useState<string | undefined>(undefined)
  const [paymentType, setPaymentType] = useState<string | undefined>(undefined)
  const [currency, setCurrency] = useState<string | undefined>(undefined)
  const [category, setCategory] = useState<string | undefined>(undefined)
  const [vendor, setVendor] = useState<string | undefined>(undefined)
  const [requester, setRequester] = useState<string | undefined>(undefined)
  const [amountMin, setAmountMin] = useState<number | null>(null)
  const [amountMax, setAmountMax] = useState<number | null>(null)
  const [submittedRange, setSubmittedRange] = useState<[Dayjs | null, Dayjs | null] | null>(null)
  const [billingRange, setBillingRange] = useState<[Dayjs | null, Dayjs | null] | null>(null)
  const [sort, setSort] = useState<SortState>({ field: null, order: null })
  const [selectedRow, setSelectedRow] = useState<RequestRow | null>(null)
  const [selectedDetail, setSelectedDetail] = useState<RequestDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)

  useEffect(() => {
    const id = window.setTimeout(() => setDebouncedSearch(search), 250)
    return () => window.clearTimeout(id)
  }, [search])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setError(null)
      setLoading(true)
      try {
        const params = new URLSearchParams()
        const submittedFrom = submittedRange?.[0]?.format('YYYY-MM-DD')
        const submittedTo = submittedRange?.[1]?.format('YYYY-MM-DD')
        const billingFrom = billingRange?.[0]?.format('YYYY-MM-DD')
        const billingTo = billingRange?.[1]?.format('YYYY-MM-DD')
        if (submittedFrom) params.set('submitted_from', submittedFrom)
        if (submittedTo) params.set('submitted_to', submittedTo)
        if (billingFrom) params.set('billing_from', billingFrom)
        if (billingTo) params.set('billing_to', billingTo)
        const query = params.toString()
        const endpoint = query ? `/api/requests/?${query}` : '/api/requests/'

        const res = await apiFetch(endpoint)
        const json = await res.json().catch(() => null)
        if (!res.ok) {
          throw new Error(typeof json === 'object' && json ? JSON.stringify(json) : `HTTP ${res.status}`)
        }
        if (!cancelled) setRows(normalizeRows(json))
      } catch (e: any) {
        if (!cancelled) setError(e?.message || 'Ошибка запроса')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [submittedRange, billingRange])

  const optionize = (values: string[]) =>
    [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b)).map((value) => ({
      label: value,
      value,
    }))

  const requesterOptions = useMemo(() => {
    const map = new Map<string, string>()
    for (const row of rows) {
      const key = row.requester !== null ? String(row.requester) : ''
      if (!key) continue
      map.set(key, row.requester_username || `User #${key}`)
    }
    return [...map.entries()].map(([value, label]) => ({ value, label }))
  }, [rows])

  const filteredRows = useMemo(() => {
    const normalizedSearch = debouncedSearch.trim().toLowerCase()
    let data = rows.filter((row) => {
      if (status && row.status !== status) return false
      if (urgency && row.urgency !== urgency) return false
      if (paymentType && row.payment_type !== paymentType) return false
      if (currency && row.currency !== currency) return false
      if (category && row.category !== category) return false
      if (vendor && row.vendor !== vendor) return false
      if (requester && String(row.requester) !== requester) return false
      if (amountMin !== null && Number(row.amount) < amountMin) return false
      if (amountMax !== null && Number(row.amount) > amountMax) return false
      if (!normalizedSearch) return true
      const haystack = `${row.title || ''} ${row.category || ''} ${row.vendor || ''} ${row.payment_purpose || ''} ${row.description || ''}`.toLowerCase()
      return haystack.includes(normalizedSearch)
    })

    if (sort.field && sort.order) {
      const dir = sort.order === 'ascend' ? 1 : -1
      data = [...data].sort((a, b) => {
        const av = a[sort.field as keyof RequestRow]
        const bv = b[sort.field as keyof RequestRow]
        if (av === bv) return 0
        if (av === null || av === undefined) return -1 * dir
        if (bv === null || bv === undefined) return 1 * dir
        if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir
        return String(av).localeCompare(String(bv)) * dir
      })
    }
    return data
  }, [rows, debouncedSearch, status, urgency, paymentType, currency, category, vendor, requester, amountMin, amountMax, sort])

  const getStatusColor = (value: string): string | undefined => {
    const normalized = String(value || '').trim().toUpperCase()
    if (normalized === 'REJECTED') return 'error'
    if (normalized === 'APPROVED') return 'success'
    if (normalized === 'PAYED') return '#8c8c8c'
    if (normalized === '1-5') return 'warning'
    const numericStatus = Number(normalized)
    if (Number.isFinite(numericStatus) && numericStatus >= 1 && numericStatus <= 5) return 'warning'
    return undefined
  }

  useEffect(() => {
    if (!selectedRow) {
      setSelectedDetail(null)
      setDetailLoading(false)
      setDetailError(null)
      return
    }
    let cancelled = false
    ;(async () => {
      setDetailLoading(true)
      setDetailError(null)
      try {
        const res = await apiFetch(`/api/requests/${selectedRow.id}/`)
        const json = (await res.json().catch(() => null)) as RequestDetail | null
        if (!res.ok) {
          throw new Error(typeof json === 'object' && json ? JSON.stringify(json) : `HTTP ${res.status}`)
        }
        if (!cancelled) setSelectedDetail(json)
      } catch (e: any) {
        if (!cancelled) setDetailError(e?.message || 'Ошибка загрузки заявки')
      } finally {
        if (!cancelled) setDetailLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [selectedRow])

  const columns: ColumnsType<RequestRow> = [
    { title: 'ID', dataIndex: 'id', width: 80, sorter: true },
    { title: 'Название', dataIndex: 'title', sorter: true },
    { title: 'Категория', dataIndex: 'category', sorter: true },
    { title: 'Поставщик', dataIndex: 'vendor', sorter: true },
    {
      title: 'Сумма',
      dataIndex: 'amount',
      sorter: true,
      render: (_, row) => `${Number(row.amount).toLocaleString('ru-RU')} ${row.currency}`,
    },
    {
      title: 'Статус',
      dataIndex: 'status',
      sorter: true,
      render: (value: string) => <Tag color={getStatusColor(value)}>{value}</Tag>,
    },
    { title: 'Срочность', dataIndex: 'urgency', sorter: true },
    { title: 'Тип оплаты', dataIndex: 'payment_type', sorter: true },
    {
      title: 'Заявитель',
      key: 'requester_label',
      sorter: true,
      render: (_, row) => row.requester_username || (row.requester ? `User #${row.requester}` : '-'),
    },
    {
      title: 'Отправлено',
      dataIndex: 'submitted_at',
      sorter: true,
      render: (value: string) => formatDateDDMMYYYY(value),
    },
    {
      title: 'Дата биллинга',
      dataIndex: 'billing_date',
      sorter: true,
      render: (value: string) => formatDateDDMMYYYY(value),
    },
  ]

  const onTableChange: TableProps<RequestRow>['onChange'] = (_, __, sorter) => {
    const normalized = Array.isArray(sorter) ? sorter[0] : sorter
    if (!normalized?.field || !normalized.order) {
      setSort({ field: null, order: null })
      return
    }
    setSort({
      field: normalized.field as keyof RequestRow,
      order: normalized.order,
    })
  }

  const decisionKey = (decision?: string | null) => String(decision || '').toLowerCase()
  const activeDetail = selectedDetail || (selectedRow ? ({ ...selectedRow, approvals: [] } as RequestDetail) : null)
  const approvals = activeDetail?.approvals || []
  const approvedApprovals = approvals.filter((a) => decisionKey(a.decision) === 'approved')
  const rejectedApprovals = approvals.filter((a) => decisionKey(a.decision) === 'rejected')
  const pendingApprovals = approvals.filter((a) => decisionKey(a.decision) === 'pending')

  const getDecisionColor = (decision?: string | null): string | undefined => {
    const key = decisionKey(decision)
    if (key === 'approved') return 'green'
    if (key === 'rejected') return 'red'
    if (key === 'pending') return 'orange'
    return 'default'
  }

  const renderApprovalGroup = (title: string, items: ApprovalItem[]) => (
    <Space direction="vertical" size={8} style={{ display: 'flex' }}>
      <Typography.Text strong>{title}</Typography.Text>
      {items.length === 0 ? (
        <Typography.Text type="secondary">Нет записей</Typography.Text>
      ) : (
        items.map((item) => (
          <Card key={item.id} size="small">
            <Space direction="vertical" size={4} style={{ display: 'flex' }}>
              <Space wrap>
                <Typography.Text>{`S${item.step}/${item.step_type}`}</Typography.Text>
                <Typography.Text>{item.approver_username || 'Unknown approver'}</Typography.Text>
                <Tag color={getDecisionColor(item.decision)}>{String(item.decision || '').toUpperCase()}</Tag>
              </Space>
              <Typography.Text type="secondary">{item.comment || 'without comment'}</Typography.Text>
              <Typography.Text type="secondary">{formatDateDDMMYYYY(item.decided_at)}</Typography.Text>
            </Space>
          </Card>
        ))
      )}
    </Space>
  )

  return (
    <Card>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Список заявок
      </Typography.Title>
      <Space direction="vertical" size={12} style={{ display: 'flex', marginTop: 12, marginBottom: 12 }}>
        <Input
          placeholder="Поиск: категория, поставщик, назначение, описание"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          allowClear
        />
        <Space wrap>
          <Select
            placeholder="Статус"
            allowClear
            style={{ width: 180 }}
            value={status}
            onChange={(value) => setStatus(value)}
            options={optionize(rows.map((r) => r.status))}
          />
          <Select
            placeholder="Срочность"
            allowClear
            style={{ width: 180 }}
            value={urgency}
            onChange={(value) => setUrgency(value)}
            options={optionize(rows.map((r) => r.urgency))}
          />
          <Select
            placeholder="Тип оплаты"
            allowClear
            style={{ width: 200 }}
            value={paymentType}
            onChange={(value) => setPaymentType(value)}
            options={optionize(rows.map((r) => r.payment_type))}
          />
          <Select
            placeholder="Валюта"
            allowClear
            style={{ width: 140 }}
            value={currency}
            onChange={(value) => setCurrency(value)}
            options={optionize(rows.map((r) => r.currency))}
          />
          <Select
            placeholder="Категория"
            allowClear
            style={{ width: 220 }}
            value={category}
            onChange={(value) => setCategory(value)}
            options={optionize(rows.map((r) => r.category))}
          />
          <Select
            placeholder="Поставщик"
            allowClear
            style={{ width: 220 }}
            value={vendor}
            onChange={(value) => setVendor(value)}
            options={optionize(rows.map((r) => r.vendor))}
          />
          <Select
            placeholder="Заявитель"
            allowClear
            style={{ width: 200 }}
            value={requester}
            onChange={(value) => setRequester(value)}
            options={requesterOptions}
          />
        </Space>
        <Space wrap>
          <DatePicker.RangePicker
            value={submittedRange}
            onChange={(value) => setSubmittedRange(value)}
            placeholder={['submitted_from', 'submitted_to']}
          />
          <DatePicker.RangePicker
            value={billingRange}
            onChange={(value) => setBillingRange(value)}
            placeholder={['billing_from', 'billing_to']}
          />
          <InputNumber
            placeholder="Мин. сумма"
            value={amountMin}
            onChange={(value) => setAmountMin(value)}
            min={0}
          />
          <InputNumber
            placeholder="Макс. сумма"
            value={amountMax}
            onChange={(value) => setAmountMax(value)}
            min={0}
          />
        </Space>
      </Space>
      {loading ? <Skeleton active style={{ marginTop: 16 }} /> : null}
      {error ? <Alert type="error" showIcon message={error} style={{ marginTop: 16 }} /> : null}
      {!loading && !error ? (
        <Table<RequestRow>
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={filteredRows}
          onChange={onTableChange}
          onRow={(record) => ({
            onClick: () => setSelectedRow(record),
            style: { cursor: 'pointer' },
          })}
          pagination={{ pageSize: 20, showSizeChanger: true }}
          scroll={{ x: 1200 }}
        />
      ) : null}
      <Modal
        open={Boolean(selectedRow)}
        title={selectedRow ? `Заявка #${selectedRow.id}` : 'Заявка'}
        footer={null}
        onCancel={() => setSelectedRow(null)}
        width={760}
      >
        {activeDetail ? (
          <Descriptions bordered size="small" column={1}>
            <Descriptions.Item label="Название">{activeDetail.title || '-'}</Descriptions.Item>
            <Descriptions.Item label="Статус">
              <Tag color={getStatusColor(activeDetail.status)}>{activeDetail.status}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="Сумма">
              {`${Number(activeDetail.amount).toLocaleString('ru-RU')} ${activeDetail.currency}`}
            </Descriptions.Item>
            <Descriptions.Item label="Категория">{activeDetail.category || '-'}</Descriptions.Item>
            <Descriptions.Item label="Поставщик">{activeDetail.vendor || '-'}</Descriptions.Item>
            <Descriptions.Item label="Назначение платежа">{activeDetail.payment_purpose || '-'}</Descriptions.Item>
            <Descriptions.Item label="Описание">{activeDetail.description || '-'}</Descriptions.Item>
            <Descriptions.Item label="Заявитель">
              {activeDetail.requester_username || (activeDetail.requester ? `User #${activeDetail.requester}` : '-')}
            </Descriptions.Item>
            <Descriptions.Item label="Отправлено">{formatDateDDMMYYYY(activeDetail.submitted_at)}</Descriptions.Item>
            <Descriptions.Item label="Дата биллинга">{formatDateDDMMYYYY(activeDetail.billing_date)}</Descriptions.Item>
            <Descriptions.Item label="Файл">
              {activeDetail.file_link ? (
                <Typography.Link href={activeDetail.file_link} target="_blank" rel="noreferrer">
                  Открыть файл
                </Typography.Link>
              ) : (
                '-'
              )}
            </Descriptions.Item>
          </Descriptions>
        ) : null}
        {detailLoading ? <Skeleton active style={{ marginTop: 12 }} /> : null}
        {detailError ? <Alert type="error" showIcon message={detailError} style={{ marginTop: 12 }} /> : null}
        {!detailLoading && activeDetail ? (
          <>
            <Divider />
            <Space direction="vertical" size={12} style={{ display: 'flex' }}>
              {renderApprovalGroup(`Одобрено (${approvedApprovals.length})`, approvedApprovals)}
              {renderApprovalGroup(`Отклонено (${rejectedApprovals.length})`, rejectedApprovals)}
              {renderApprovalGroup(`В ожидании (${pendingApprovals.length})`, pendingApprovals)}
            </Space>
          </>
        ) : null}
      </Modal>
    </Card>
  )
}

