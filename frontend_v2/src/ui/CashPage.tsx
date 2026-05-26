import { useEffect, useMemo, useState } from 'react'
import { useInfiniteList } from '../lib/useInfiniteList'
import { ListInfiniteScrollFooter } from './ListInfiniteScrollFooter'
import { Alert, Button, Card, Collapse, DatePicker, Descriptions, Modal, Input, InputNumber, Select, Skeleton, Space, Switch, Table, Tabs, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { Dayjs } from 'dayjs'
import { useNavigate } from 'react-router-dom'
import { FileSearchOutlined, MessageOutlined } from '@ant-design/icons'
import { apiFetch, getCashRegisters, getCashRevenues, type CashRevenue } from '../lib/api'
import type { RequestReturnTo } from '../lib/requestNavigation'
import { RequestDetailModal, type RequestDetail } from './requests/RequestDetailModal'
import { NoteCreateModal } from './NoteCreateModal'
import { labelBlockAboveField } from './formSpacing'
import { ChannelBalancesSummary } from './ChannelBalancesSummary'
import { renderExpenseRequestStatusTag, shouldHighlightMissingRequiredRequest } from './expenseRequestStatus'

type CashExpenseRow = {
  id: number
  external_id: string
  confirmed?: boolean
  title: string
  amount: string | number
  currency: string
  expense_at: string | null
  expense_year: number
  expense_month: number
  expense_day: number
  note: string
  has_request?: boolean
  has_paid_request?: boolean
  matched_request_id?: number | null
  request_required?: boolean
  wallet_id?: number | null
  created_at: string
}

type CashRevenueRow = CashRevenue

function normalizeRows(payload: unknown): CashExpenseRow[] {
  if (Array.isArray(payload)) return payload as CashExpenseRow[]
  if (payload && typeof payload === 'object' && 'results' in payload) {
    const results = (payload as { results?: unknown }).results
    return Array.isArray(results) ? (results as CashExpenseRow[]) : []
  }
  return []
}

const dateTimeFormatterTashkent = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  timeZone: 'Asia/Tashkent',
})

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

function formatDateTime(value?: string | null): string {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '-'
  return dateTimeFormatterTashkent.format(parsed)
}

export function CashPage() {
  const navigate = useNavigate()
  const [missingRequestOnly, setMissingRequestOnly] = useState(false)
  const [revenues, setRevenues] = useState<CashRevenueRow[]>([])
  const [revenuesLoading, setRevenuesLoading] = useState(true)
  const [cashRegisterByWalletId, setCashRegisterByWalletId] = useState<Record<number, string>>({})
  const [search, setSearch] = useState('')
  const [confirmedFilter, setConfirmedFilter] = useState<string | undefined>(undefined)
  const [currencyFilter, setCurrencyFilter] = useState<string | undefined>(undefined)
  const [cashRegisterFilter, setCashRegisterFilter] = useState<string | undefined>(undefined)
  const [amountMin, setAmountMin] = useState<number | null>(null)
  const [amountMax, setAmountMax] = useState<number | null>(null)
  const [dateRange, setDateRange] = useState<[Dayjs | null, Dayjs | null] | null>(null)
  const [currentAllPage, setCurrentAllPage] = useState(1)
  const [allPageSize, setAllPageSize] = useState(10)
  const [currentPage, setCurrentPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [currentRevenuePage, setCurrentRevenuePage] = useState(1)
  const [revenuePageSize, setRevenuePageSize] = useState(10)
  const [selectedExpense, setSelectedExpense] = useState<CashExpenseRow | null>(null)
  const [selectedRevenue, setSelectedRevenue] = useState<CashRevenueRow | null>(null)
  const [requestDetail, setRequestDetail] = useState<RequestDetail | null>(null)
  const [requestLoading, setRequestLoading] = useState(false)
  const [requestError, setRequestError] = useState<string | null>(null)
  const [openFullRequestModal, setOpenFullRequestModal] = useState(false)
  const [openNoteModal, setOpenNoteModal] = useState(false)

  const expenseListUrl = useMemo(() => {
    const params = new URLSearchParams()
    if (currencyFilter) params.set('currency', currencyFilter)
    if (cashRegisterFilter) params.set('wallet', cashRegisterFilter)
    if (amountMin !== null) params.set('amount_min', String(amountMin))
    if (amountMax !== null) params.set('amount_max', String(amountMax))
    const from = dateRange?.[0]?.format('YYYY-MM-DD')
    const to = dateRange?.[1]?.format('YYYY-MM-DD')
    if (from) params.set('expense_from', from)
    if (to) params.set('expense_to', to)
    if (search.trim()) params.set('search', search.trim())
    if (missingRequestOnly) params.set('missing_request', '1')
    const q = params.toString()
    return q ? `/api/cash/expenses/?${q}` : '/api/cash/expenses/'
  }, [currencyFilter, cashRegisterFilter, amountMin, amountMax, dateRange, search, missingRequestOnly])

  const {
    items: rows,
    loading,
    loadingMore,
    error,
    hasMore: expensesHasMore,
    sentinelRef: expensesSentinelRef,
  } = useInfiniteList<CashExpenseRow>({ url: expenseListUrl })

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const [revenueRows, cashRegisters] = await Promise.all([getCashRevenues(), getCashRegisters()])
        if (!cancelled) {
          setRevenues(revenueRows)
          const byWallet: Record<number, string> = {}
          for (const reg of cashRegisters) {
            byWallet[reg.wallet_id] = reg.name || `Касса #${reg.id}`
          }
          setCashRegisterByWalletId(byWallet)
        }
      } catch {
        // revenues/registers are auxiliary; expense list errors come from useInfiniteList
      } finally {
        if (!cancelled) setRevenuesLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const cashRegisterNameByWallet = (walletId?: number | null): string => {
    if (!walletId) return '-'
    return cashRegisterByWalletId[walletId] || `Кошелек #${walletId}`
  }

  const optionize = (values: string[]) =>
    [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b)).map((value) => ({ label: value, value }))

  const passesCommonFilters = (
    row: { currency?: string; wallet_id?: number | null; at?: string | null; amountNum: number; confirmed?: boolean },
    normalized: string,
    haystack: string,
  ) => {
    if (currencyFilter && row.currency !== currencyFilter) return false
    if (cashRegisterFilter && cashRegisterNameByWallet(row.wallet_id) !== cashRegisterFilter) return false
    if (confirmedFilter === 'confirmed' && row.confirmed === false) return false
    if (confirmedFilter === 'unconfirmed' && row.confirmed !== false) return false
    if (amountMin !== null && row.amountNum < amountMin) return false
    if (amountMax !== null && row.amountNum > amountMax) return false
    const from = dateRange?.[0]?.format('YYYY-MM-DD')
    const to = dateRange?.[1]?.format('YYYY-MM-DD')
    const currentDate = String(row.at || '').slice(0, 10)
    if (from && (!currentDate || currentDate < from)) return false
    if (to && (!currentDate || currentDate > to)) return false
    if (!normalized) return true
    return haystack.includes(normalized)
  }

  const allRows = useMemo(() => {
    const expenseRows = rows.map((e) => ({
      kind: 'expense' as const,
      id: e.id,
      displayId: e.external_id || String(e.id),
      title: e.title,
      amount: e.amount,
      currency: e.currency,
      at: e.expense_at,
      note: e.note,
      raw: e,
    }))
    const revenueRows = revenues.map((r) => ({
      kind: 'revenue' as const,
      id: r.id,
      displayId: r.external_id || String(r.id),
      title: r.operation || '-',
      amount: r.total_sum ?? 0,
      currency: r.currency,
      at: r.revenue_at || r.created_at,
      note: r.comment || '',
      raw: r,
    }))
    return [...expenseRows, ...revenueRows].sort((a, b) => String(b.at || '').localeCompare(String(a.at || '')))
  }, [rows, revenues])

  const filteredRows = useMemo(() => {
    const normalized = search.trim().toLowerCase()
    return rows.filter((row) => {
      const haystack = JSON.stringify(row).toLowerCase()
      return passesCommonFilters(
        {
          currency: row.currency,
          wallet_id: row.wallet_id,
          at: row.expense_at,
          amountNum: Number(row.amount),
          confirmed: row.confirmed,
        },
        normalized,
        haystack,
      )
    })
  }, [rows, search, currencyFilter, cashRegisterFilter, confirmedFilter, amountMin, amountMax, dateRange])

  const filteredRevenueRows = useMemo(() => {
    const normalized = search.trim().toLowerCase()
    return revenues.filter((row) => {
      const haystack = JSON.stringify(row).toLowerCase()
      return passesCommonFilters(
        {
          currency: row.currency,
          wallet_id: row.wallet_id,
          at: row.revenue_at || row.created_at,
          amountNum: Number(row.total_sum || 0),
          confirmed: row.confirmed,
        },
        normalized,
        haystack,
      )
    })
  }, [revenues, search, currencyFilter, cashRegisterFilter, confirmedFilter, amountMin, amountMax, dateRange])

  const filteredAllRows = useMemo(() => {
    const normalized = search.trim().toLowerCase()
    return allRows.filter((row) => {
      const haystack = JSON.stringify(row).toLowerCase()
      const raw = row.raw as CashExpenseRow | CashRevenueRow
      const isExpense = row.kind === 'expense'
      const amountNum = Number(row.amount || 0)
      const confirmed = isExpense ? (raw as CashExpenseRow).confirmed : (raw as CashRevenueRow).confirmed
      return passesCommonFilters(
        {
          currency: row.currency,
          wallet_id: raw.wallet_id,
          at: row.at,
          amountNum,
          confirmed,
        },
        normalized,
        haystack,
      )
    })
  }, [allRows, search, currencyFilter, cashRegisterFilter, confirmedFilter, amountMin, amountMax, dateRange])

  useEffect(() => {
    setCurrentAllPage(1)
    setCurrentPage(1)
    setCurrentRevenuePage(1)
  }, [search, confirmedFilter, currencyFilter, cashRegisterFilter, amountMin, amountMax, dateRange])

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

  const columns: ColumnsType<CashExpenseRow> = [
    {
      title: 'ID',
      dataIndex: 'external_id',
      width: 120,
      sorter: (a, b) => String(a.external_id || '').localeCompare(String(b.external_id || '')),
    },
    { title: 'Название', dataIndex: 'title', sorter: (a, b) => String(a.title).localeCompare(String(b.title)) },
    {
      title: 'Статус заявки',
      dataIndex: 'has_paid_request',
      width: 150,
      render: (_value: boolean | undefined, row) => renderExpenseRequestStatusTag(row),
    },
    {
      title: 'Подтверждено',
      dataIndex: 'confirmed',
      width: 130,
      render: (value: boolean | undefined) =>
        value === false ? <Tag color="default">Нет</Tag> : <Tag color="success">Да</Tag>,
    },
    {
      title: 'Сумма',
      dataIndex: 'amount',
      sorter: (a, b) => Number(a.amount) - Number(b.amount),
      render: (_, row) => `${Number(row.amount).toLocaleString('ru-RU')} ${row.currency || ''}`.trim(),
    },
    {
      title: 'Касса',
      dataIndex: 'wallet_id',
      width: 220,
      render: (_: number | undefined, row) => cashRegisterNameByWallet(row.wallet_id),
      sorter: (a, b) => cashRegisterNameByWallet(a.wallet_id).localeCompare(cashRegisterNameByWallet(b.wallet_id)),
    },
    {
      title: 'Дата/время расхода',
      dataIndex: 'expense_at',
      sorter: (a, b) => String(a.expense_at || '').localeCompare(String(b.expense_at || '')),
      render: (value: string | null) => formatDateTime(value),
    },
    { title: 'Год', dataIndex: 'expense_year', width: 90, sorter: (a, b) => a.expense_year - b.expense_year },
    { title: 'Месяц', dataIndex: 'expense_month', width: 90, sorter: (a, b) => a.expense_month - b.expense_month },
    { title: 'День', dataIndex: 'expense_day', width: 90, sorter: (a, b) => a.expense_day - b.expense_day },
    {
      title: 'Создано',
      dataIndex: 'created_at',
      sorter: (a, b) => String(a.created_at || '').localeCompare(String(b.created_at || '')),
      render: (value: string) => formatDateTime(value),
    },
    { title: 'Примечание', dataIndex: 'note' },
  ]

  const revenueColumns: ColumnsType<CashRevenueRow> = [
    { title: 'ID', dataIndex: 'id', width: 90, sorter: (a, b) => a.id - b.id },
    {
      title: 'External ID',
      dataIndex: 'external_id',
      width: 140,
      sorter: (a, b) => String(a.external_id || '').localeCompare(String(b.external_id || '')),
      render: (value: string | undefined) => value || '-',
    },
    { title: 'Операция', dataIndex: 'operation', sorter: (a, b) => String(a.operation || '').localeCompare(String(b.operation || '')) },
    {
      title: 'Сумма',
      dataIndex: 'total_sum',
      sorter: (a, b) => Number(a.total_sum || 0) - Number(b.total_sum || 0),
      render: (_, row) => `${Number(row.total_sum || 0).toLocaleString('ru-RU')} ${row.currency || ''}`.trim(),
    },
    {
      title: 'Касса',
      dataIndex: 'wallet_id',
      width: 220,
      render: (value: number | undefined) => cashRegisterNameByWallet(value ?? null),
      sorter: (a, b) => cashRegisterNameByWallet(a.wallet_id).localeCompare(cashRegisterNameByWallet(b.wallet_id)),
    },
    { title: 'Дата/время', dataIndex: 'revenue_at', render: (value: string | null | undefined) => formatDateTime(value || null) },
    { title: 'Контрагент', dataIndex: 'counterparty' },
    {
      title: 'Подтверждено',
      dataIndex: 'confirmed',
      width: 130,
      render: (value: boolean | undefined) =>
        value === false ? <Tag color="default">Нет</Tag> : <Tag color="success">Да</Tag>,
    },
    { title: 'Комментарий', dataIndex: 'comment' },
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
    {
      title: 'ID',
      dataIndex: 'displayId',
      width: 120,
      sorter: (a, b) => String(a.displayId || '').localeCompare(String(b.displayId || '')),
    },
    { title: 'Название', dataIndex: 'title', sorter: (a, b) => String(a.title || '').localeCompare(String(b.title || '')) },
    {
      title: 'Сумма',
      dataIndex: 'amount',
      sorter: (a, b) => Number(a.amount) - Number(b.amount),
      render: (_, row) => `${Number(row.amount).toLocaleString('ru-RU')} ${row.currency || ''}`.trim(),
    },
    {
      title: 'Дата',
      dataIndex: 'at',
      sorter: (a, b) => String(a.at || '').localeCompare(String(b.at || '')),
      render: (value: string | null) => formatDate(value),
    },
    { title: 'Примечание', dataIndex: 'note' },
  ]

  return (
    <Card>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Касса
      </Typography.Title>
      <ChannelBalancesSummary channel="cash" />
      <div style={{ marginTop: 12, marginBottom: 12 }}>
        <Typography.Text type="secondary" style={labelBlockAboveField}>
          Расходы и доходы
        </Typography.Text>
        <Input
          placeholder="Поиск: ID, название, примечание"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          allowClear
          style={{ width: 320 }}
        />
        <Collapse
          size="small"
          style={{ marginTop: 8 }}
          items={[
            {
              key: 'advanced',
              label: (() => {
                const count = [confirmedFilter, currencyFilter, cashRegisterFilter, amountMin, amountMax, dateRange, missingRequestOnly].filter(Boolean).length
                return count > 0 ? `Расширенные фильтры (${count} активно)` : 'Расширенные фильтры'
              })(),
              children: (
                <Space wrap size={[12, 12]}>
                  <Select
                    placeholder="Подтверждение"
                    allowClear
                    style={{ width: 180 }}
                    value={confirmedFilter}
                    onChange={setConfirmedFilter}
                    options={[
                      { value: 'confirmed', label: 'Подтверждено' },
                      { value: 'unconfirmed', label: 'Не подтверждено' },
                    ]}
                  />
                  <Select
                    placeholder="Валюта"
                    allowClear
                    style={{ width: 140 }}
                    value={currencyFilter}
                    onChange={setCurrencyFilter}
                    options={optionize(allRows.map((r) => r.currency || ''))}
                  />
                  <Select
                    placeholder="Касса"
                    allowClear
                    style={{ width: 240 }}
                    value={cashRegisterFilter}
                    onChange={setCashRegisterFilter}
                    options={optionize(
                      Array.from(new Set(allRows.map((r) => cashRegisterNameByWallet((r.raw as CashExpenseRow | CashRevenueRow).wallet_id)))),
                    )}
                  />
                  <DatePicker.RangePicker value={dateRange} onChange={(v) => setDateRange(v)} placeholder={['Дата от', 'Дата до']} />
                  <InputNumber placeholder="Мин. сумма" min={0} value={amountMin} onChange={setAmountMin} />
                  <InputNumber placeholder="Макс. сумма" min={0} value={amountMax} onChange={setAmountMax} />
                  <Space align="center">
                    <Typography.Text style={{ marginBottom: 0 }}>Без заявки (обязательна)</Typography.Text>
                    <Switch checked={missingRequestOnly} onChange={setMissingRequestOnly} />
                  </Space>
                  <Button
                    onClick={() => {
                      setConfirmedFilter(undefined)
                      setCurrencyFilter(undefined)
                      setCashRegisterFilter(undefined)
                      setAmountMin(null)
                      setAmountMax(null)
                      setDateRange(null)
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
                  columns={allColumns}
                  dataSource={filteredAllRows}
                  size="small"
                  pagination={{
                    current: currentAllPage,
                    pageSize: allPageSize,
                    showSizeChanger: true,
                    pageSizeOptions: [10, 20, 50, 100, 200],
                  }}
                  onChange={(pagination) => {
                    if (pagination.current) setCurrentAllPage(pagination.current)
                    if (pagination.pageSize) setAllPageSize(pagination.pageSize)
                  }}
                  onRow={(record) => ({
                    onClick: () => {
                      if (record.kind === 'expense') setSelectedExpense(record.raw as CashExpenseRow)
                      else setSelectedRevenue(record.raw as CashRevenueRow)
                    },
                    style: { cursor: 'pointer' },
                  })}
                  scroll={{ x: 900 }}
                />
              ),
            },
            {
              key: 'expenses',
              label: 'Расходы',
              children: (
                <>
                  <Table<CashExpenseRow>
                    rowKey="id"
                    columns={columns}
                    dataSource={filteredRows}
                    size="small"
                    rowClassName={(record) => {
                      if (record.confirmed === false) return 'cash-row-unconfirmed'
                      if (shouldHighlightMissingRequiredRequest(record)) return 'cash-row-unmatched'
                      return ''
                    }}
                    pagination={false}
                    onRow={(record) => ({
                      onClick: () => setSelectedExpense(record),
                      style: { cursor: 'pointer' },
                    })}
                    scroll={{ x: 1100 }}
                  />
                  <ListInfiniteScrollFooter
                    sentinelRef={expensesSentinelRef}
                    hasMore={expensesHasMore}
                    loadingMore={loadingMore}
                    visibleCount={filteredRows.length}
                  />
                </>
              ),
            },
            {
              key: 'revenues',
              label: 'Доходы',
              children: (
                <Table<CashRevenueRow>
                  rowKey="id"
                  columns={revenueColumns}
                  dataSource={filteredRevenueRows}
                  size="small"
                  pagination={{
                    current: currentRevenuePage,
                    pageSize: revenuePageSize,
                    showSizeChanger: true,
                    pageSizeOptions: [10, 20, 50, 100, 200],
                  }}
                  onChange={(pagination) => {
                    if (pagination.current) setCurrentRevenuePage(pagination.current)
                    if (pagination.pageSize) setRevenuePageSize(pagination.pageSize)
                  }}
                  onRow={(record) => ({
                    onClick: () => setSelectedRevenue(record),
                    style: { cursor: 'pointer' },
                  })}
                  scroll={{ x: 1200 }}
                />
              ),
            },
          ]}
        />
      ) : null}
      <Modal
        open={Boolean(selectedExpense)}
        title={selectedExpense ? `Кассовый расход #${selectedExpense.id}` : 'Кассовый расход'}
        footer={null}
        onCancel={() => {
          setSelectedExpense(null)
          setOpenFullRequestModal(false)
        }}
        width={760}
      >
        {selectedExpense ? (
          <Space style={{ marginBottom: 12 }}>
            <Button icon={<FileSearchOutlined />} onClick={() => navigate(`/cash/${selectedExpense.id}`)}>
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
            <Descriptions.Item label="ID">{selectedExpense.external_id || '-'}</Descriptions.Item>
            <Descriptions.Item label="Подтверждено">
              {selectedExpense.confirmed === false ? <Tag color="default">Нет</Tag> : <Tag color="processing">Да</Tag>}
            </Descriptions.Item>
            <Descriptions.Item label="Название">{selectedExpense.title || '-'}</Descriptions.Item>
            <Descriptions.Item label="Сумма">
              {`${Number(selectedExpense.amount).toLocaleString('ru-RU')} ${selectedExpense.currency || ''}`.trim()}
            </Descriptions.Item>
            <Descriptions.Item label="Касса">{cashRegisterNameByWallet(selectedExpense.wallet_id)}</Descriptions.Item>
            <Descriptions.Item label="Дата/время расхода">{formatDateTime(selectedExpense.expense_at)}</Descriptions.Item>
            <Descriptions.Item label="Примечание">{selectedExpense.note || '-'}</Descriptions.Item>
            <Descriptions.Item label="Статус заявки">
              {renderExpenseRequestStatusTag(selectedExpense)}
            </Descriptions.Item>
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
        title={selectedRevenue ? `Кассовый доход #${selectedRevenue.id}` : 'Кассовый доход'}
        footer={null}
        onCancel={() => setSelectedRevenue(null)}
        width={760}
      >
        {selectedRevenue ? (
          <Descriptions bordered size="small" column={1}>
            <Descriptions.Item label="ID">{selectedRevenue.id}</Descriptions.Item>
            <Descriptions.Item label="Внешний ID">{selectedRevenue.external_id || '-'}</Descriptions.Item>
            <Descriptions.Item label="Операция">{selectedRevenue.operation || '-'}</Descriptions.Item>
            <Descriptions.Item label="Сумма">
              {`${Number(selectedRevenue.total_sum || 0).toLocaleString('ru-RU')} ${selectedRevenue.currency || ''}`.trim()}
            </Descriptions.Item>
            <Descriptions.Item label="Касса">{cashRegisterNameByWallet(selectedRevenue.wallet_id)}</Descriptions.Item>
            <Descriptions.Item label="Дата/время">{formatDateTime(selectedRevenue.revenue_at || null)}</Descriptions.Item>
            <Descriptions.Item label="Контрагент">{selectedRevenue.counterparty || '-'}</Descriptions.Item>
            <Descriptions.Item label="Подтверждено">
              {selectedRevenue.confirmed === false ? <Tag color="default">Нет</Tag> : <Tag color="processing">Да</Tag>}
            </Descriptions.Item>
            <Descriptions.Item label="Комментарий">{selectedRevenue.comment || '-'}</Descriptions.Item>
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
                pathname: selectedExpense ? `/cash/${selectedExpense.id}` : '/cash',
                label: selectedExpense ? `Кассовый расход #${selectedExpense.id}` : 'Касса',
              } satisfies RequestReturnTo)
            : undefined
        }
      />
      <NoteCreateModal
        open={openNoteModal}
        onCancel={() => setOpenNoteModal(false)}
        targetType="cash"
        targetId={selectedExpense?.id || null}
      />
      <style>{`
        .cash-row-unmatched > td {
          background: #fffbe6 !important;
        }
        .cash-row-unconfirmed > td {
          background: #fafafa !important;
          color: #bfbfbf !important;
          opacity: 0.6;
        }
      `}</style>
    </Card>
  )
}

