import { useMemo, useState } from 'react'
import { useFinanceInfiniteScrollFooter } from '../lib/useFinanceInfiniteScrollFooter'
import { useInfiniteList } from '../lib/useInfiniteList'
import { ListInfiniteScrollFooter } from './ListInfiniteScrollFooter'
import { Alert, Button, Card, Collapse, DatePicker, Descriptions, Input, InputNumber, Select, Modal, Skeleton, Space, Table, Tag, Typography } from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import type { Dayjs } from 'dayjs'
import { useNavigate } from 'react-router-dom'
import type { CorporateCardExpense, CorporateCardRevenue } from '../lib/api'
import { labelBlockAboveField } from './formSpacing'
import { ChannelBalancesSummary } from './ChannelBalancesSummary'
import { renderExpenseRequestStatusTag, shouldHighlightMissingRequiredRequest } from './expenseRequestStatus'

const dateTimeFormatterTashkent = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  timeZone: 'Asia/Tashkent',
})

function formatDateTime(value?: string | null): string {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '-'
  return dateTimeFormatterTashkent.format(parsed)
}

export type CorporateCardSectionMode = 'all' | 'expenses' | 'revenues'

const SECTION_TITLES: Record<CorporateCardSectionMode, string> = {
  all: 'Корпоративная карта — все операции',
  expenses: 'Корпоративная карта — расходы',
  revenues: 'Корпоративная карта — доходы',
}

export function CorporateCardSectionPage({ mode }: { mode: CorporateCardSectionMode }) {
  const navigate = useNavigate()
  const needExpenses = mode !== 'revenues'
  const needRevenues = mode !== 'expenses'
  const [search, setSearch] = useState('')
  const [currencyFilter, setCurrencyFilter] = useState<string | undefined>(undefined)
  const [confirmedFilter, setConfirmedFilter] = useState<string | undefined>(undefined)
  const [amountMin, setAmountMin] = useState<number | null>(null)
  const [amountMax, setAmountMax] = useState<number | null>(null)
  const [dateRange, setDateRange] = useState<[Dayjs | null, Dayjs | null] | null>(null)
  const [selectedExpense, setSelectedExpense] = useState<CorporateCardExpense | null>(null)
  const [selectedRevenue, setSelectedRevenue] = useState<CorporateCardRevenue | null>(null)

  const expenseListUrl = useMemo(() => {
    const params = new URLSearchParams()
    if (search.trim()) params.set('search', search.trim())
    const from = dateRange?.[0]?.format('YYYY-MM-DD')
    const to = dateRange?.[1]?.format('YYYY-MM-DD')
    if (from) params.set('expense_from', from)
    if (to) params.set('expense_to', to)
    if (amountMin !== null) params.set('amount_min', String(amountMin))
    if (amountMax !== null) params.set('amount_max', String(amountMax))
    const q = params.toString()
    return q ? `/api/corporate-card/expenses/?${q}` : '/api/corporate-card/expenses/'
  }, [search, dateRange, amountMin, amountMax])

  const revenueListUrl = useMemo(() => {
    const params = new URLSearchParams()
    const from = dateRange?.[0]?.format('YYYY-MM-DD')
    const to = dateRange?.[1]?.format('YYYY-MM-DD')
    if (from) params.set('expense_from', from)
    if (to) params.set('expense_to', to)
    const q = params.toString()
    return q ? `/api/corporate-card/revenues/?${q}` : '/api/corporate-card/revenues/'
  }, [dateRange])

  const {
    items: expenses,
    loading: expensesLoading,
    loadingMore: expensesLoadingMore,
    error: expensesError,
    hasMore: expensesHasMore,
    loadMore: loadMoreExpenses,
  } = useInfiniteList<CorporateCardExpense>({ url: expenseListUrl, enabled: needExpenses })

  const {
    items: revenues,
    loading: revenuesLoading,
    loadingMore: revenuesLoadingMore,
    error: revenuesError,
    hasMore: revenuesHasMore,
    loadMore: loadMoreRevenues,
  } = useInfiniteList<CorporateCardRevenue>({ url: revenueListUrl, enabled: needRevenues })

  const listLoading = (needExpenses && expensesLoading) || (needRevenues && revenuesLoading)
  const listError = expensesError || revenuesError
  const listHasMore = (needExpenses && expensesHasMore) || (needRevenues && revenuesHasMore)
  const listLoadingMore = (needExpenses && expensesLoadingMore) || (needRevenues && revenuesLoadingMore)

  const loadMoreAll = () => {
    if (needExpenses && expensesHasMore) loadMoreExpenses()
    if (needRevenues && revenuesHasMore) loadMoreRevenues()
  }

  const listSentinelRef = useFinanceInfiniteScrollFooter({
    hasMore: listHasMore,
    loadingMore: listLoadingMore,
    onLoadMore: loadMoreAll,
  })

  const optionize = (values: string[]) =>
    [...new Set(values.filter(Boolean))].sort().map((value) => ({ value, label: value }))

  const normalizedSearch = search.trim().toLowerCase()

  const allRows = useMemo(() => {
    const expenseRows = expenses.map((e) => ({
      kind: 'expense' as const,
      id: e.id,
      title: e.title || '',
      amount: e.amount,
      currency: e.currency,
      at: e.expense_at,
      note: e.note,
      raw: e,
    }))
    const revenueRows = revenues.map((r) => ({
      kind: 'revenue' as const,
      id: r.id,
      title: r.title || r.external_id || '',
      amount: r.amount,
      currency: r.currency,
      at: r.revenue_at,
      note: r.note || '',
      raw: r,
    }))
    return [...expenseRows, ...revenueRows].sort((a, b) => String(b.at || '').localeCompare(String(a.at || '')))
  }, [expenses, revenues])

  const filteredAllRows = useMemo(() => {
    return allRows.filter((row) => {
      const raw = row.raw as CorporateCardExpense | CorporateCardRevenue
      const confirmed = 'confirmed' in raw ? raw.confirmed : undefined
      if (currencyFilter && row.currency !== currencyFilter) return false
      if (confirmedFilter === 'confirmed' && confirmed === false) return false
      if (confirmedFilter === 'unconfirmed' && confirmed !== false) return false
      if (amountMin !== null && Number(row.amount) < amountMin) return false
      if (amountMax !== null && Number(row.amount) > amountMax) return false
      const from = dateRange?.[0]?.format('YYYY-MM-DD')
      const to = dateRange?.[1]?.format('YYYY-MM-DD')
      const currentDate = String(row.at || '').slice(0, 10)
      if (from && (!currentDate || currentDate < from)) return false
      if (to && (!currentDate || currentDate > to)) return false
      if (!normalizedSearch) return true
      const haystack = JSON.stringify(row).toLowerCase()
      return haystack.includes(normalizedSearch)
    })
  }, [allRows, normalizedSearch, currencyFilter, confirmedFilter, amountMin, amountMax, dateRange])

  const filteredExpenses = useMemo(() => {
    return expenses.filter((row) => {
      if (currencyFilter && row.currency !== currencyFilter) return false
      if (amountMin !== null && Number(row.amount) < amountMin) return false
      if (amountMax !== null && Number(row.amount) > amountMax) return false
      const from = dateRange?.[0]?.format('YYYY-MM-DD')
      const to = dateRange?.[1]?.format('YYYY-MM-DD')
      const currentDate = String(row.expense_at || '').slice(0, 10)
      if (from && (!currentDate || currentDate < from)) return false
      if (to && (!currentDate || currentDate > to)) return false
      if (!normalizedSearch) return true
      const haystack = JSON.stringify(row).toLowerCase()
      return haystack.includes(normalizedSearch)
    })
  }, [expenses, normalizedSearch, currencyFilter, amountMin, amountMax, dateRange])

  const filteredRevenues = useMemo(() => {
    return revenues.filter((row) => {
      if (currencyFilter && row.currency !== currencyFilter) return false
      if (confirmedFilter === 'confirmed' && row.confirmed === false) return false
      if (confirmedFilter === 'unconfirmed' && row.confirmed !== false) return false
      if (amountMin !== null && Number(row.amount) < amountMin) return false
      if (amountMax !== null && Number(row.amount) > amountMax) return false
      const from = dateRange?.[0]?.format('YYYY-MM-DD')
      const to = dateRange?.[1]?.format('YYYY-MM-DD')
      const currentDate = String(row.revenue_at || '').slice(0, 10)
      if (from && (!currentDate || currentDate < from)) return false
      if (to && (!currentDate || currentDate > to)) return false
      if (!normalizedSearch) return true
      const haystack = JSON.stringify(row).toLowerCase()
      return haystack.includes(normalizedSearch)
    })
  }, [revenues, normalizedSearch, currencyFilter, confirmedFilter, amountMin, amountMax, dateRange])

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
    { title: 'ID', dataIndex: 'id', width: 90, sorter: (a, b) => a.id - b.id },
    { title: 'Название', dataIndex: 'title', sorter: (a, b) => String(a.title || '').localeCompare(String(b.title || '')) },
    {
      title: 'Сумма',
      dataIndex: 'amount',
      sorter: (a, b) => Number(a.amount) - Number(b.amount),
      render: (_, row) => `${Number(row.amount).toLocaleString('ru-RU')} ${row.currency || ''}`.trim(),
    },
    {
      title: 'Дата/время',
      dataIndex: 'at',
      sorter: (a, b) => String(a.at || '').localeCompare(String(b.at || '')),
      render: (value: string) => formatDateTime(value),
    },
    { title: 'Примечание', dataIndex: 'note' },
  ]

  const expenseColumns: ColumnsType<CorporateCardExpense> = [
    { title: 'ID', dataIndex: 'id', width: 90, sorter: (a, b) => a.id - b.id },
    { title: 'Название', dataIndex: 'title', sorter: (a, b) => String(a.title || '').localeCompare(String(b.title || '')) },
    {
      title: 'Сумма',
      dataIndex: 'amount',
      sorter: (a, b) => Number(a.amount) - Number(b.amount),
      render: (_, row) => `${Number(row.amount).toLocaleString('ru-RU')} ${row.currency || ''}`.trim(),
    },
    {
      title: 'Статус заявки',
      dataIndex: 'has_paid_request',
      width: 180,
      render: (_value, row) => renderExpenseRequestStatusTag(row),
    },
    {
      title: 'Дата расхода',
      dataIndex: 'expense_at',
      sorter: (a, b) => String(a.expense_at || '').localeCompare(String(b.expense_at || '')),
      render: (value: string) => formatDateTime(value),
    },
    { title: 'Примечание', dataIndex: 'note' },
  ]

  const revenueColumns: ColumnsType<CorporateCardRevenue> = [
    { title: 'ID', dataIndex: 'id', width: 90, sorter: (a, b) => a.id - b.id },
    {
      title: 'Внешний ID',
      dataIndex: 'external_id',
      width: 120,
      sorter: (a, b) => String(a.external_id || '').localeCompare(String(b.external_id || '')),
    },
    { title: 'Название', dataIndex: 'title', sorter: (a, b) => String(a.title || '').localeCompare(String(b.title || '')) },
    {
      title: 'Сумма',
      dataIndex: 'amount',
      sorter: (a, b) => Number(a.amount) - Number(b.amount),
      render: (_, row) => `${Number(row.amount).toLocaleString('ru-RU')} ${row.currency || ''}`.trim(),
    },
    {
      title: 'Подтв.',
      dataIndex: 'confirmed',
      width: 100,
      render: (value: boolean | undefined) => (value === false ? <Tag color="default">Нет</Tag> : <Tag color="processing">Да</Tag>),
    },
    {
      title: 'Дата',
      dataIndex: 'revenue_at',
      sorter: (a, b) => String(a.revenue_at || '').localeCompare(String(b.revenue_at || '')),
      render: (value: string) => formatDateTime(value),
    },
    { title: 'Примечание', dataIndex: 'note' },
  ]

  return (
    <Card>
      <Space style={{ marginBottom: 12 }}>
        <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/corporate-card')}>
          Корпоративная карта
        </Button>
      </Space>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        {SECTION_TITLES[mode]}
      </Typography.Title>
      <ChannelBalancesSummary channel="corporate_card" />
      <div style={{ marginTop: 8, marginBottom: 12 }}>
        <Typography.Text type="secondary" style={labelBlockAboveField}>
          Расходы и пополнения корпоративной карты
        </Typography.Text>
        <Input
          placeholder="Поиск: ID, название, внешний ID, примечание"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          allowClear
          style={{ width: 420 }}
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
                  <DatePicker.RangePicker value={dateRange} onChange={setDateRange} placeholder={['Дата от', 'Дата до']} />
                  <InputNumber placeholder="Мин. сумма" min={0} value={amountMin} onChange={setAmountMin} />
                  <InputNumber placeholder="Макс. сумма" min={0} value={amountMax} onChange={setAmountMax} />
                  <Button
                    onClick={() => {
                      setCurrencyFilter(undefined)
                      setConfirmedFilter(undefined)
                      setAmountMin(null)
                      setAmountMax(null)
                      setDateRange(null)
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

      {listLoading ? <Skeleton active style={{ marginTop: 16 }} /> : null}
      {listError ? <Alert type="error" showIcon message={listError} style={{ marginTop: 16, marginBottom: 16 }} /> : null}

      {!listLoading && !listError && mode === 'all' ? (
        <Table<AllRow>
          rowKey={(r) => `${r.kind}:${r.id}`}
          size="small"
          columns={allColumns}
          dataSource={filteredAllRows}
          style={{ marginTop: 16 }}
          onRow={(record) => ({
            onClick: () => {
              if (record.kind === 'expense') setSelectedExpense(record.raw as CorporateCardExpense)
              else setSelectedRevenue(record.raw as CorporateCardRevenue)
            },
            style: { cursor: 'pointer' },
          })}
          pagination={false}
          scroll={{ x: 1100 }}
        />
      ) : null}
      {!listLoading && !listError && mode === 'expenses' ? (
        <Table<CorporateCardExpense>
          rowKey="id"
          size="small"
          columns={expenseColumns}
          dataSource={filteredExpenses}
          style={{ marginTop: 16 }}
          rowClassName={(record) => (shouldHighlightMissingRequiredRequest(record) ? 'card-row-unmatched' : '')}
          pagination={false}
          onRow={(record) => ({
            onClick: () => setSelectedExpense(record),
            style: { cursor: 'pointer' },
          })}
          scroll={{ x: 980 }}
        />
      ) : null}
      {!listLoading && !listError && mode === 'revenues' ? (
        <Table<CorporateCardRevenue>
          rowKey="id"
          size="small"
          columns={revenueColumns}
          dataSource={filteredRevenues}
          style={{ marginTop: 16 }}
          pagination={false}
          onRow={(record) => ({
            onClick: () => setSelectedRevenue(record),
            style: { cursor: 'pointer' },
          })}
          scroll={{ x: 1100 }}
        />
      ) : null}

      {(mode === 'all' || mode === 'expenses' || mode === 'revenues') && !listLoading && !listError ? (
        <ListInfiniteScrollFooter
          sentinelRef={listSentinelRef}
          hasMore={listHasMore}
          loadingMore={listLoadingMore}
          visibleCount={
            mode === 'expenses'
              ? filteredExpenses.length
              : mode === 'revenues'
                ? filteredRevenues.length
                : filteredAllRows.length
          }
          loadedCount={mode === 'expenses' ? expenses.length : mode === 'revenues' ? revenues.length : expenses.length + revenues.length}
          onLoadMore={loadMoreAll}
        />
      ) : null}

      <Modal
        open={Boolean(selectedExpense)}
        title={selectedExpense ? `Расход по карте #${selectedExpense.id}` : 'Расход по карте'}
        footer={null}
        onCancel={() => setSelectedExpense(null)}
      >
        {selectedExpense ? (
          <Descriptions bordered size="small" column={1}>
            <Descriptions.Item label="ID">{selectedExpense.id}</Descriptions.Item>
            <Descriptions.Item label="Название">{selectedExpense.title || '-'}</Descriptions.Item>
            <Descriptions.Item label="Сумма">
              {`${Number(selectedExpense.amount).toLocaleString('ru-RU')} ${selectedExpense.currency || ''}`.trim()}
            </Descriptions.Item>
            <Descriptions.Item label="Дата расхода">{formatDateTime(selectedExpense.expense_at)}</Descriptions.Item>
            <Descriptions.Item label="Примечание">{selectedExpense.note || '-'}</Descriptions.Item>
            <Descriptions.Item label="Статус заявки">{renderExpenseRequestStatusTag(selectedExpense)}</Descriptions.Item>
            <Descriptions.Item label="Связанная заявка">
              {selectedExpense.matched_request_id ? `#${selectedExpense.matched_request_id}` : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="Создано">{formatDateTime(selectedExpense.created_at)}</Descriptions.Item>
          </Descriptions>
        ) : null}
        {selectedExpense?.matched_request_id ? (
          <Space style={{ marginTop: 12 }}>
            <Button type="primary" onClick={() => navigate(`/requests/${selectedExpense.matched_request_id}`)}>
              Открыть связанную заявку
            </Button>
          </Space>
        ) : null}
      </Modal>

      <Modal
        open={Boolean(selectedRevenue)}
        title={selectedRevenue ? `Доход по карте #${selectedRevenue.id}` : 'Доход по карте'}
        footer={null}
        onCancel={() => setSelectedRevenue(null)}
      >
        {selectedRevenue ? (
          <Descriptions bordered size="small" column={1}>
            <Descriptions.Item label="ID">{selectedRevenue.id}</Descriptions.Item>
            <Descriptions.Item label="Внешний ID">{selectedRevenue.external_id || '-'}</Descriptions.Item>
            <Descriptions.Item label="Название">{selectedRevenue.title || '-'}</Descriptions.Item>
            <Descriptions.Item label="Сумма">
              {`${Number(selectedRevenue.amount).toLocaleString('ru-RU')} ${selectedRevenue.currency || ''}`.trim()}
            </Descriptions.Item>
            <Descriptions.Item label="Дата">{formatDateTime(selectedRevenue.revenue_at)}</Descriptions.Item>
            <Descriptions.Item label="Подтверждено">
              {selectedRevenue.confirmed === false ? <Tag color="default">Нет</Tag> : <Tag color="processing">Да</Tag>}
            </Descriptions.Item>
            <Descriptions.Item label="Примечание">{selectedRevenue.note || '-'}</Descriptions.Item>
            <Descriptions.Item label="Создано">{formatDateTime(selectedRevenue.created_at)}</Descriptions.Item>
          </Descriptions>
        ) : null}
      </Modal>
      <style>{`
        .card-row-unmatched > td {
          background: #fffbe6 !important;
        }
      `}</style>
    </Card>
  )
}
