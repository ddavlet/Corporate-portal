import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Collapse, DatePicker, Descriptions, Input, InputNumber, Select, Modal, Skeleton, Space, Switch, Table, Tag, Tooltip, Typography } from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import type { Dayjs } from 'dayjs'
import { useNavigate } from 'react-router-dom'
import { FileSearchOutlined, MessageOutlined } from '@ant-design/icons'
import { apiFetch, getBankRevenues, type BankRevenue } from '../lib/api'
import { useInfiniteList } from '../lib/useInfiniteList'
import { ListInfiniteScrollFooter } from './ListInfiniteScrollFooter'
import type { RequestReturnTo } from '../lib/requestNavigation'
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
  account_name?: string
  vendor_name?: string | null
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

function compareDateStrings(a?: string | null, b?: string | null): number {
  return String(a || '').slice(0, 10).localeCompare(String(b || '').slice(0, 10))
}

function getExpenseCounterparty(row: BankExpenseRow): string {
  return String(row.vendor_name || '').trim()
}

export type BankSectionMode = 'all' | 'expenses' | 'revenues'

const SECTION_TITLES: Record<BankSectionMode, string> = {
  all: 'Банк — все операции',
  expenses: 'Банк — расходы',
  revenues: 'Банк — доходы',
}

export function BankSectionPage({ mode }: { mode: BankSectionMode }) {
  const navigate = useNavigate()
  const needExpenses = mode !== 'revenues'
  const needRevenues = mode !== 'expenses'
  const [missingRequestOnly, setMissingRequestOnly] = useState(false)
  const [revenues, setRevenues] = useState<BankRevenueRow[]>([])
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

  const expenseListUrl = useMemo(() => {
    const params = new URLSearchParams()
    if (search.trim()) params.set('search', search.trim())
    if (counterpartyFilter) params.set('vendor_search', counterpartyFilter)
    const docFrom = docDateRange?.[0]?.format('YYYY-MM-DD')
    const docTo = docDateRange?.[1]?.format('YYYY-MM-DD')
    if (docFrom) params.set('doc_from', docFrom)
    if (docTo) params.set('doc_to', docTo)
    if (amountMin !== null) params.set('amount_min', String(amountMin))
    if (amountMax !== null) params.set('amount_max', String(amountMax))
    if (missingRequestOnly) params.set('missing_request', '1')
    const q = params.toString()
    return q ? `/api/bank/expenses/?${q}` : '/api/bank/expenses/'
  }, [search, counterpartyFilter, docDateRange, amountMin, amountMax, missingRequestOnly])

  const {
    items: rows,
    loading,
    loadingMore,
    error,
    hasMore: expensesHasMore,
    loadMore: loadMoreExpenses,
    sentinelRef: expensesSentinelRef,
  } = useInfiniteList<BankExpenseRow>({ url: expenseListUrl, enabled: needExpenses })

  useEffect(() => {
    if (!needRevenues) return
    let cancelled = false
    ;(async () => {
      try {
        const revenueRows = await getBankRevenues()
        if (!cancelled) setRevenues(revenueRows)
      } catch {
        // auxiliary
      }
    })()
    return () => {
      cancelled = true
    }
  }, [needRevenues])

  const allRows = useMemo(() => {
    const expenseRows = rows.map((e) => ({
      kind: 'expense' as const,
      id: e.id,
      doc_no: e.doc_no,
      account_name: getExpenseCounterparty(e),
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
      if (counterpartyFilter && getExpenseCounterparty(row) !== counterpartyFilter) return false
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
    { title: 'Контрагент', key: 'counterparty', render: (_, row) => getExpenseCounterparty(row) || '-' },
    {
      title: <Tooltip title="Дата документа из банковской выписки">Дата документа</Tooltip>,
      dataIndex: 'doc_date',
      defaultSortOrder: 'descend',
      sorter: (a, b) => compareDateStrings(a.doc_date, b.doc_date),
      render: (value: string) => formatDate(value),
    },
    {
      title: <Tooltip title="Дата учётной проводки в системе">Дата проводки</Tooltip>,
      dataIndex: 'process_date',
      sorter: (a, b) => compareDateStrings(a.process_date, b.process_date),
      render: (value: string) => formatDate(value),
    },
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
    {
      title: <Tooltip title="Дата документа из банковской выписки">Дата документа</Tooltip>,
      dataIndex: 'doc_date',
      defaultSortOrder: 'descend',
      sorter: (a, b) => compareDateStrings(a.doc_date, b.doc_date),
      render: (value: string) => formatDate(value),
    },
    {
      title: <Tooltip title="Дата учётной проводки в системе">Дата проводки</Tooltip>,
      dataIndex: 'process_date',
      sorter: (a, b) => compareDateStrings(a.process_date, b.process_date),
      render: (value: string) => formatDate(value),
    },
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
    {
      title: 'Дата док.',
      dataIndex: 'at',
      defaultSortOrder: 'descend',
      sorter: (a, b) => compareDateStrings(a.at, b.at),
      render: (value: string) => formatDate(value),
    },
  ]

  const showExpenseInfiniteFooter = needExpenses && (mode === 'expenses' || mode === 'all')

  return (
    <Card>
      <Space style={{ marginBottom: 12 }}>
        <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/bank')}>
          Банк
        </Button>
      </Space>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        {SECTION_TITLES[mode]}
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
                  {needExpenses ? (
                    <Space align="center">
                      <Typography.Text style={{ marginBottom: 0 }}>Без заявки (обязательна)</Typography.Text>
                      <Switch checked={missingRequestOnly} onChange={setMissingRequestOnly} />
                    </Space>
                  ) : null}
                  <Button
                    onClick={() => {
                      setCounterpartyFilter(undefined)
                      setAmountMin(null)
                      setAmountMax(null)
                      setDocDateRange(null)
                      setMissingRequestOnly(false)
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
      {needExpenses && loading ? <Skeleton active style={{ marginTop: 16 }} /> : null}
      {needExpenses && error ? <Alert type="error" showIcon message={error} style={{ marginTop: 16 }} /> : null}
      {needExpenses && !loading && !error && mode === 'all' ? (
        <Table<AllRow>
          rowKey={(r) => `${r.kind}:${r.id}`}
          size="small"
          columns={allColumns}
          dataSource={filteredAllRows}
          style={{ marginTop: 16 }}
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
      ) : null}
      {needExpenses && !loading && !error && mode === 'expenses' ? (
        <Table<BankExpenseRow>
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={filteredRows}
          style={{ marginTop: 16 }}
          rowClassName={(record) => (shouldHighlightMissingRequiredRequest(record) ? 'bank-row-unmatched' : '')}
          onRow={(record) => ({
            onClick: () => setSelectedExpense(record),
            style: { cursor: 'pointer' },
          })}
          pagination={false}
          scroll={{ x: 1100 }}
        />
      ) : null}
      {needRevenues && !needExpenses ? (
        <Table<BankRevenueRow>
          rowKey="id"
          size="small"
          columns={revenueColumns}
          dataSource={filteredRevenueRows}
          style={{ marginTop: 16 }}
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
      ) : null}
      {showExpenseInfiniteFooter && !loading && !error ? (
        <ListInfiniteScrollFooter
          sentinelRef={expensesSentinelRef}
          hasMore={expensesHasMore}
          loadingMore={loadingMore}
          visibleCount={mode === 'expenses' ? filteredRows.length : rows.length}
          loadedCount={rows.length}
          onLoadMore={loadMoreExpenses}
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
            <Button icon={<FileSearchOutlined />} onClick={() => navigate(`/bank/expenses/${selectedExpense.id}`)}>
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
            <Descriptions.Item label="Контрагент">{getExpenseCounterparty(selectedExpense) || '-'}</Descriptions.Item>
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
        returnTo={
          requestDetail?.id
            ? ({
                pathname: selectedExpense ? `/bank/expenses/${selectedExpense.id}` : '/bank',
                label: selectedExpense ? `Банковский расход #${selectedExpense.id}` : 'Банк',
              } satisfies RequestReturnTo)
            : undefined
        }
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

