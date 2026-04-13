import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Collapse, DatePicker, Descriptions, Input, InputNumber, Select, Modal, Skeleton, Space, Table, Tabs, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { Dayjs } from 'dayjs'
import { useNavigate } from 'react-router-dom'
import { FileSearchOutlined, MessageOutlined } from '@ant-design/icons'
import { apiFetch, getBankRevenues, type BankRevenue } from '../lib/api'
import { RequestDetailModal, type RequestDetail } from './requests/RequestDetailModal'
import { NoteCreateModal } from './NoteCreateModal'
import { labelBlockAboveField } from './formSpacing'
import { ChannelBalancesSummary } from './ChannelBalancesSummary'
import { renderExpenseRequestStatusTag, shouldHighlightMissingRequiredRequest } from './expenseRequestStatus'

type BankExpenseRow = {
  id: number
  row_no?: number | null
  doc_date: string
  process_date: string
  doc_no: string
  account_name: string
  inn?: string | null
  account_no: string
  mfo: string
  debit_turnover: string | number
  payment_purpose: string
  has_request?: boolean
  has_paid_request?: boolean
  matched_request_id?: number | null
  request_required?: boolean
}

type BankRevenueRow = BankRevenue

function normalizeRows(payload: unknown): BankExpenseRow[] {
  if (Array.isArray(payload)) return payload as BankExpenseRow[]
  if (payload && typeof payload === 'object' && 'results' in payload) {
    const results = (payload as { results?: unknown }).results
    return Array.isArray(results) ? (results as BankExpenseRow[]) : []
  }
  return []
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

export function BankPage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [rows, setRows] = useState<BankExpenseRow[]>([])
  const [revenues, setRevenues] = useState<BankRevenueRow[]>([])
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [counterpartyFilter, setCounterpartyFilter] = useState<string | undefined>(undefined)
  const [amountMin, setAmountMin] = useState<number | null>(null)
  const [amountMax, setAmountMax] = useState<number | null>(null)
  const [docDateRange, setDocDateRange] = useState<[Dayjs | null, Dayjs | null] | null>(null)
  const [currentAllPage, setCurrentAllPage] = useState(1)
  const [allPageSize, setAllPageSize] = useState(20)
  const [currentExpensePage, setCurrentExpensePage] = useState(1)
  const [expensePageSize, setExpensePageSize] = useState(20)
  const [currentRevenuePage, setCurrentRevenuePage] = useState(1)
  const [revenuePageSize, setRevenuePageSize] = useState(20)
  const [selectedExpense, setSelectedExpense] = useState<BankExpenseRow | null>(null)
  const [selectedRevenue, setSelectedRevenue] = useState<BankRevenueRow | null>(null)
  const [requestDetail, setRequestDetail] = useState<RequestDetail | null>(null)
  const [requestLoading, setRequestLoading] = useState(false)
  const [requestError, setRequestError] = useState<string | null>(null)
  const [openFullRequestModal, setOpenFullRequestModal] = useState(false)
  const [openNoteModal, setOpenNoteModal] = useState(false)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setError(null)
      setLoading(true)
      try {
        const [res, revenueRows] = await Promise.all([apiFetch('/api/bank/expenses/'), getBankRevenues()])
        const json = await res.json().catch(() => null)
        if (!res.ok) {
          throw new Error(typeof json === 'object' && json ? JSON.stringify(json) : `HTTP ${res.status}`)
        }
        if (!cancelled) {
          const normalized = normalizeRows(json)
          setRows(normalized)
          setRevenues(revenueRows)
        }
      } catch (e: any) {
        if (!cancelled) setError(e?.message || 'Ошибка запроса')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const allRows = useMemo(() => {
    const expenseRows = rows.map((e) => ({
      kind: 'expense' as const,
      id: e.id,
      doc_no: e.doc_no,
      account_name: e.account_name,
      amount: e.debit_turnover,
      at: e.doc_date,
      purpose: e.payment_purpose,
      raw: e,
    }))
    const revenueRows = revenues.map((r) => ({
      kind: 'revenue' as const,
      id: r.id,
      doc_no: r.doc_no,
      account_name: r.account_name,
      amount: r.kredit_turnover,
      at: r.doc_date,
      purpose: r.payment_purpose,
      raw: r,
    }))
    return [...expenseRows, ...revenueRows].sort((a, b) => String(b.at || '').localeCompare(String(a.at || '')))
  }, [rows, revenues])

  useEffect(() => {
    if (!selectedExpense?.matched_request_id) {
      setRequestDetail(null)
      setRequestError(null)
      setRequestLoading(false)
      return
    }
    let cancelled = false
    ;(async () => {
      setRequestLoading(true)
      setRequestError(null)
      try {
        const res = await apiFetch(`/api/requests/${selectedExpense.matched_request_id}/`)
        const json = (await res.json().catch(() => null)) as RequestDetail | null
        if (!res.ok) {
          throw new Error(typeof json === 'object' && json ? JSON.stringify(json) : `HTTP ${res.status}`)
        }
        if (!cancelled) setRequestDetail(json)
      } catch (e: any) {
        if (!cancelled) setRequestError(e?.message || 'Ошибка загрузки заявки')
      } finally {
        if (!cancelled) setRequestLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [selectedExpense?.matched_request_id])

  const optionize = (values: string[]) =>
    [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b)).map((value) => ({ label: value, value }))

  const filteredRows = useMemo(() => {
    const normalized = search.trim().toLowerCase()
    return rows.filter((row) => {
      if (counterpartyFilter && row.account_name !== counterpartyFilter) return false
      if (amountMin !== null && Number(row.debit_turnover) < amountMin) return false
      if (amountMax !== null && Number(row.debit_turnover) > amountMax) return false
      const from = docDateRange?.[0]?.format('YYYY-MM-DD')
      const to = docDateRange?.[1]?.format('YYYY-MM-DD')
      const current = String(row.doc_date || '').slice(0, 10)
      if (from && (!current || current < from)) return false
      if (to && (!current || current > to)) return false
      if (!normalized) return true
      const haystack = JSON.stringify(row).toLowerCase()
      return haystack.includes(normalized)
    })
  }, [rows, search, counterpartyFilter, amountMin, amountMax, docDateRange])

  const filteredRevenueRows = useMemo(() => {
    const normalized = search.trim().toLowerCase()
    return revenues.filter((row) => {
      if (counterpartyFilter && row.account_name !== counterpartyFilter) return false
      if (amountMin !== null && Number(row.kredit_turnover) < amountMin) return false
      if (amountMax !== null && Number(row.kredit_turnover) > amountMax) return false
      const from = docDateRange?.[0]?.format('YYYY-MM-DD')
      const to = docDateRange?.[1]?.format('YYYY-MM-DD')
      const current = String(row.doc_date || '').slice(0, 10)
      if (from && (!current || current < from)) return false
      if (to && (!current || current > to)) return false
      if (!normalized) return true
      const haystack = JSON.stringify(row).toLowerCase()
      return haystack.includes(normalized)
    })
  }, [revenues, search, counterpartyFilter, amountMin, amountMax, docDateRange])

  const filteredAllRows = useMemo(() => {
    const normalized = search.trim().toLowerCase()
    return allRows.filter((row) => {
      if (counterpartyFilter && row.account_name !== counterpartyFilter) return false
      if (amountMin !== null && Number(row.amount) < amountMin) return false
      if (amountMax !== null && Number(row.amount) > amountMax) return false
      const from = docDateRange?.[0]?.format('YYYY-MM-DD')
      const to = docDateRange?.[1]?.format('YYYY-MM-DD')
      const current = String(row.at || '').slice(0, 10)
      if (from && (!current || current < from)) return false
      if (to && (!current || current > to)) return false
      if (!normalized) return true
      const haystack = JSON.stringify(row).toLowerCase()
      return haystack.includes(normalized)
    })
  }, [allRows, search, counterpartyFilter, amountMin, amountMax, docDateRange])

  useEffect(() => {
    setCurrentAllPage(1)
    setCurrentExpensePage(1)
    setCurrentRevenuePage(1)
  }, [search, counterpartyFilter, amountMin, amountMax, docDateRange])

  const columns: ColumnsType<BankExpenseRow> = [
    { title: 'PK', dataIndex: 'id', width: 80, sorter: (a, b) => a.id - b.id },
    { title: 'Док. №', dataIndex: 'doc_no', sorter: (a, b) => String(a.doc_no || '').localeCompare(String(b.doc_no || '')) },
    {
      title: 'Сумма',
      dataIndex: 'debit_turnover',
      sorter: (a, b) => Number(a.debit_turnover) - Number(b.debit_turnover),
      render: (value: string | number) => Number(value).toLocaleString('ru-RU'),
    },
    {
      title: 'Статус заявки',
      dataIndex: 'has_paid_request',
      width: 150,
      render: (_value: boolean | undefined, row) => renderExpenseRequestStatusTag(row),
    },
    { title: 'Контрагент', dataIndex: 'account_name' },
    { title: 'Дата док.', dataIndex: 'doc_date', render: (value: string) => formatDate(value) },
    { title: 'Дата проводки', dataIndex: 'process_date', render: (value: string) => formatDate(value) },
  ]

  const revenueColumns: ColumnsType<BankRevenueRow> = [
    { title: 'PK', dataIndex: 'id', width: 80, sorter: (a, b) => a.id - b.id },
    { title: 'Док. №', dataIndex: 'doc_no', sorter: (a, b) => String(a.doc_no || '').localeCompare(String(b.doc_no || '')) },
    {
      title: 'Сумма',
      dataIndex: 'kredit_turnover',
      sorter: (a, b) => Number(a.kredit_turnover) - Number(b.kredit_turnover),
      render: (value: string | number) => Number(value).toLocaleString('ru-RU'),
    },
    { title: 'Контрагент', dataIndex: 'account_name' },
    { title: 'Дата док.', dataIndex: 'doc_date', render: (value: string) => formatDate(value) },
    { title: 'Дата проводки', dataIndex: 'process_date', render: (value: string) => formatDate(value) },
  ]

  type AllRow = (typeof allRows)[number]
  const allColumns: ColumnsType<AllRow> = [
    {
      title: 'Тип',
      dataIndex: 'kind',
      width: 100,
      render: (value: 'expense' | 'revenue') =>
        value === 'expense' ? <Tag color="gold">Расход</Tag> : <Tag color="green">Доход</Tag>,
      sorter: (a, b) => String(a.kind).localeCompare(String(b.kind)),
    },
    { title: 'ID', dataIndex: 'doc_no', width: 140, sorter: (a, b) => String(a.doc_no || '').localeCompare(String(b.doc_no || '')) },
    {
      title: 'Сумма',
      dataIndex: 'amount',
      sorter: (a, b) => Number(a.amount) - Number(b.amount),
      render: (value: string | number) => Number(value).toLocaleString('ru-RU'),
    },
    { title: 'Контрагент', dataIndex: 'account_name' },
    { title: 'Дата док.', dataIndex: 'at', render: (value: string) => formatDate(value) },
  ]

  return (
    <Card>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Банк
      </Typography.Title>
      <ChannelBalancesSummary channel="bank" />
      <div style={{ marginTop: 12, marginBottom: 12 }}>
        <Typography.Text type="secondary" style={labelBlockAboveField}>
          Расходы и доходы
        </Typography.Text>
        <Input
          placeholder="Поиск: номер документа, контрагент, назначение"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          allowClear
          style={{ width: 360 }}
        />
        <Collapse
          size="small"
          style={{ marginTop: 8 }}
          items={[
            {
              key: 'advanced',
              label: 'Расширенные фильтры',
              children: (
                <Space wrap size={[12, 12]}>
                  <Select
                    placeholder="Контрагент"
                    allowClear
                    style={{ width: 260 }}
                    value={counterpartyFilter}
                    onChange={setCounterpartyFilter}
                    options={optionize(allRows.map((r) => r.account_name || ''))}
                  />
                  <DatePicker.RangePicker value={docDateRange} onChange={setDocDateRange} placeholder={['Дата док. от', 'Дата док. до']} />
                  <InputNumber placeholder="Мин. сумма" min={0} value={amountMin} onChange={setAmountMin} />
                  <InputNumber placeholder="Макс. сумма" min={0} value={amountMax} onChange={setAmountMax} />
                  <Button
                    onClick={() => {
                      setCounterpartyFilter(undefined)
                      setAmountMin(null)
                      setAmountMax(null)
                      setDocDateRange(null)
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
      {loading ? <Skeleton active style={{ marginTop: 16 }} /> : null}
      {error ? <Alert type="error" showIcon message={error} style={{ marginTop: 16 }} /> : null}
      {!loading && !error ? (
        <Tabs
          items={[
            {
              key: 'all',
              label: 'Все',
              children: (
                <Table<AllRow>
                  rowKey={(r) => `${r.kind}:${r.id}`}
                  size="small"
                  columns={allColumns}
                  dataSource={filteredAllRows}
                  onRow={(record) => ({
                    onClick: () => {
                      if (record.kind === 'expense') setSelectedExpense(record.raw as BankExpenseRow)
                      else setSelectedRevenue(record.raw as BankRevenueRow)
                    },
                    style: { cursor: 'pointer' },
                  })}
                  pagination={{
                    current: currentAllPage,
                    pageSize: allPageSize,
                    showSizeChanger: true,
                    pageSizeOptions: [20, 50, 100, 200],
                  }}
                  onChange={(pagination) => {
                    if (pagination.current) setCurrentAllPage(pagination.current)
                    if (pagination.pageSize) setAllPageSize(pagination.pageSize)
                  }}
                  scroll={{ x: 1100 }}
                />
              ),
            },
            {
              key: 'expenses',
              label: 'Расходы',
              children: (
                <Table<BankExpenseRow>
                  rowKey="id"
                  size="small"
                  columns={columns}
                  dataSource={filteredRows}
                  rowClassName={(record) => (shouldHighlightMissingRequiredRequest(record) ? 'bank-row-unmatched' : '')}
                  onRow={(record) => ({
                    onClick: () => setSelectedExpense(record),
                    style: { cursor: 'pointer' },
                  })}
                  pagination={{
                    current: currentExpensePage,
                    pageSize: expensePageSize,
                    showSizeChanger: true,
                    pageSizeOptions: [20, 50, 100, 200],
                  }}
                  onChange={(pagination) => {
                    if (pagination.current) setCurrentExpensePage(pagination.current)
                    if (pagination.pageSize) setExpensePageSize(pagination.pageSize)
                  }}
                  scroll={{ x: 1100 }}
                />
              ),
            },
            {
              key: 'revenues',
              label: 'Доходы',
              children: (
                <Table<BankRevenueRow>
                  rowKey="id"
                  size="small"
                  columns={revenueColumns}
                  dataSource={filteredRevenueRows}
                  onRow={(record) => ({
                    onClick: () => setSelectedRevenue(record),
                    style: { cursor: 'pointer' },
                  })}
                  pagination={{
                    current: currentRevenuePage,
                    pageSize: revenuePageSize,
                    showSizeChanger: true,
                    pageSizeOptions: [20, 50, 100, 200],
                  }}
                  onChange={(pagination) => {
                    if (pagination.current) setCurrentRevenuePage(pagination.current)
                    if (pagination.pageSize) setRevenuePageSize(pagination.pageSize)
                  }}
                  scroll={{ x: 1100 }}
                />
              ),
            },
          ]}
        />
      ) : null}

      <Modal
        open={Boolean(selectedExpense)}
        title={selectedExpense ? `Банковский расход #${selectedExpense.id}` : 'Банковский расход'}
        footer={null}
        onCancel={() => {
          setSelectedExpense(null)
          setOpenFullRequestModal(false)
        }}
        width={760}
      >
        {selectedExpense ? (
          <Space style={{ marginBottom: 12 }}>
            <Button icon={<FileSearchOutlined />} onClick={() => navigate(`/bank/${selectedExpense.id}`)}>
              Открыть страницу
            </Button>
            <Button icon={<MessageOutlined />} onClick={() => setOpenNoteModal(true)}>
              Добавить заметку
            </Button>
          </Space>
        ) : null}
        {selectedExpense ? (
          <Descriptions bordered size="small" column={1}>
            <Descriptions.Item label="PK">{selectedExpense.id}</Descriptions.Item>
            <Descriptions.Item label="Док. №">{selectedExpense.doc_no || '-'}</Descriptions.Item>
            <Descriptions.Item label="Контрагент">{selectedExpense.account_name || '-'}</Descriptions.Item>
            <Descriptions.Item label="Сумма">{Number(selectedExpense.debit_turnover).toLocaleString('ru-RU')}</Descriptions.Item>
            <Descriptions.Item label="Назначение">{selectedExpense.payment_purpose || '-'}</Descriptions.Item>
            <Descriptions.Item label="Дата док.">{formatDate(selectedExpense.doc_date)}</Descriptions.Item>
            <Descriptions.Item label="Дата проводки">{formatDate(selectedExpense.process_date)}</Descriptions.Item>
            <Descriptions.Item label="Статус заявки">{renderExpenseRequestStatusTag(selectedExpense)}</Descriptions.Item>
          </Descriptions>
        ) : null}

        <Typography.Title level={5} style={{ marginTop: 16, marginBottom: 8 }}>
          Связанная заявка
        </Typography.Title>
        {!selectedExpense?.matched_request_id ? (
          <Alert type="info" showIcon message="Связанная заявка не найдена." />
        ) : requestLoading ? (
          <Skeleton active />
        ) : requestError ? (
          <Alert type="error" showIcon message={requestError} />
        ) : requestDetail ? (
          <Space direction="vertical" size={8} style={{ display: 'flex' }}>
            <Descriptions bordered size="small" column={1}>
              <Descriptions.Item label="ID">{requestDetail.id}</Descriptions.Item>
              <Descriptions.Item label="Название">{requestDetail.title || '-'}</Descriptions.Item>
              <Descriptions.Item label="Статус">{requestDetail.status || '-'}</Descriptions.Item>
              <Descriptions.Item label="Сумма">
                {`${Number(requestDetail.amount).toLocaleString('ru-RU')} ${requestDetail.currency || ''}`.trim()}
              </Descriptions.Item>
            </Descriptions>
            <Button type="primary" onClick={() => setOpenFullRequestModal(true)}>
              Открыть заявку полностью
            </Button>
            {requestDetail?.id ? (
              <Button onClick={() => navigate(`/requests/${requestDetail.id}`)}>Открыть страницу заявки</Button>
            ) : null}
          </Space>
        ) : null}
      </Modal>

      <Modal
        open={Boolean(selectedRevenue)}
        title={selectedRevenue ? `Банковский доход #${selectedRevenue.id}` : 'Банковский доход'}
        footer={null}
        onCancel={() => setSelectedRevenue(null)}
        width={760}
      >
        {selectedRevenue ? (
          <Descriptions bordered size="small" column={1}>
            <Descriptions.Item label="PK">{selectedRevenue.id}</Descriptions.Item>
            <Descriptions.Item label="Док. №">{selectedRevenue.doc_no || '-'}</Descriptions.Item>
            <Descriptions.Item label="Контрагент">{selectedRevenue.account_name || '-'}</Descriptions.Item>
            <Descriptions.Item label="Сумма">{Number(selectedRevenue.kredit_turnover).toLocaleString('ru-RU')}</Descriptions.Item>
            <Descriptions.Item label="Назначение">{selectedRevenue.payment_purpose || '-'}</Descriptions.Item>
            <Descriptions.Item label="Дата док.">{formatDate(selectedRevenue.doc_date)}</Descriptions.Item>
            <Descriptions.Item label="Дата проводки">{formatDate(selectedRevenue.process_date)}</Descriptions.Item>
          </Descriptions>
        ) : null}
      </Modal>

      <RequestDetailModal
        open={openFullRequestModal}
        onCancel={() => setOpenFullRequestModal(false)}
        detail={requestDetail}
        loading={requestLoading}
        error={requestError}
      />
      <NoteCreateModal
        open={openNoteModal}
        onCancel={() => setOpenNoteModal(false)}
        targetType="bank"
        targetId={selectedExpense?.id || null}
      />
      <style>{`
        .bank-row-unmatched > td {
          background: #fffbe6 !important;
        }
      `}</style>
    </Card>
  )
}

