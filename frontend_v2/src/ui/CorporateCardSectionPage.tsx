import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Collapse, DatePicker, Descriptions, Input, InputNumber, Select, Modal, Skeleton, Space, Table, Tag, Typography } from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import type { Dayjs } from 'dayjs'
import { useNavigate } from 'react-router-dom'
import {
  getCorporateCardExpenses,
  getCorporateCardRevenues,
  type CorporateCardExpense,
  type CorporateCardRevenue,
} from '../lib/api'
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

function formatDate(value?: string | null): string {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '-'
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    timeZone: 'Asia/Tashkent',
  }).format(parsed)
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
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expenses, setExpenses] = useState<CorporateCardExpense[]>([])
  const [revenues, setRevenues] = useState<CorporateCardRevenue[]>([])
  const [search, setSearch] = useState('')
  const [currencyFilter, setCurrencyFilter] = useState<string | undefined>(undefined)
  const [confirmedFilter, setConfirmedFilter] = useState<string | undefined>(undefined)
  const [operationFilter, setOperationFilter] = useState<string | undefined>(undefined)
  const [counterpartyFilter, setCounterpartyFilter] = useState<string | undefined>(undefined)
  const [amountMin, setAmountMin] = useState<number | null>(null)
  const [amountMax, setAmountMax] = useState<number | null>(null)
  const [dateRange, setDateRange] = useState<[Dayjs | null, Dayjs | null] | null>(null)
  const [currentExpensePage, setCurrentExpensePage] = useState(1)
  const [expensePageSize, setExpensePageSize] = useState(10)
  const [currentRevenuePage, setCurrentRevenuePage] = useState(1)
  const [revenuePageSize, setRevenuePageSize] = useState(10)
  const [currentAllPage, setCurrentAllPage] = useState(1)
  const [allPageSize, setAllPageSize] = useState(10)
  const [selectedExpense, setSelectedExpense] = useState<CorporateCardExpense | null>(null)
  const [selectedRevenue, setSelectedRevenue] = useState<CorporateCardRevenue | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setError(null)
      try {
        const [expenseRows, revenueRows] = await Promise.all([
          needExpenses ? getCorporateCardExpenses() : Promise.resolve([] as CorporateCardExpense[]),
          needRevenues ? getCorporateCardRevenues() : Promise.resolve([] as CorporateCardRevenue[]),
        ])
        if (!cancelled) {
          setExpenses(expenseRows)
          setRevenues(revenueRows)
        }
      } catch (e: any) {
        if (!cancelled) setError(e?.message || 'Ошибка загрузки corporate card данных')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [needExpenses, needRevenues])

  const normalizedSearch = search.trim().toLowerCase()
  const optionize = (values: string[]) =>
    [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b)).map((value) => ({ label: value, value }))

  const allRows = useMemo(() => {
    const expenseRows = expenses.map((e) => ({
      kind: 'expense' as const,
      id: e.id,
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
      title: r.title || r.external_id || '',
      amount: r.total_sum ?? r.amount,
      currency: r.currency,
      at: r.revenue_at,
      note: r.comment || r.note || '',
      raw: r,
    }))
    return [...expenseRows, ...revenueRows].sort((a, b) => String(b.at || '').localeCompare(String(a.at || '')))
  }, [expenses, revenues])

  const filteredAllRows = useMemo(() => {
    return allRows.filter((row) => {
      const raw = row.raw as CorporateCardExpense | CorporateCardRevenue
      const op = (raw as CorporateCardRevenue).operation || ''
      const cp = (raw as CorporateCardRevenue).counterparty || ''
      const confirmed = (raw as CorporateCardRevenue).confirmed
      if (currencyFilter && row.currency !== currencyFilter) return false
      if (operationFilter && op !== operationFilter) return false
      if (counterpartyFilter && cp !== counterpartyFilter) return false
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
  }, [allRows, normalizedSearch, currencyFilter, operationFilter, counterpartyFilter, confirmedFilter, amountMin, amountMax, dateRange])

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
      if (operationFilter && (row.operation || '') !== operationFilter) return false
      if (counterpartyFilter && (row.counterparty || '') !== counterpartyFilter) return false
      if (confirmedFilter === 'confirmed' && row.confirmed === false) return false
      if (confirmedFilter === 'unconfirmed' && row.confirmed !== false) return false
      if (amountMin !== null && Number(row.total_sum ?? row.amount) < amountMin) return false
      if (amountMax !== null && Number(row.total_sum ?? row.amount) > amountMax) return false
      const from = dateRange?.[0]?.format('YYYY-MM-DD')
      const to = dateRange?.[1]?.format('YYYY-MM-DD')
      const currentDate = String(row.revenue_at || row.revenue_date || '').slice(0, 10)
      if (from && (!currentDate || currentDate < from)) return false
      if (to && (!currentDate || currentDate > to)) return false
      if (!normalizedSearch) return true
      const haystack = JSON.stringify(row).toLowerCase()
      return haystack.includes(normalizedSearch)
    })
  }, [revenues, normalizedSearch, currencyFilter, operationFilter, counterpartyFilter, confirmedFilter, amountMin, amountMax, dateRange])

  useEffect(() => {
    setCurrentAllPage(1)
    setCurrentExpensePage(1)
    setCurrentRevenuePage(1)
  }, [search, currencyFilter, confirmedFilter, operationFilter, counterpartyFilter, amountMin, amountMax, dateRange])

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
    {
      title: 'Дата',
      dataIndex: 'revenue_date',
      sorter: (a, b) => String(a.revenue_date || '').localeCompare(String(b.revenue_date || '')),
      render: (value: string | null | undefined, row) => formatDate(value || row.revenue_at),
    },
    {
      title: 'Подтв.',
      dataIndex: 'confirmed',
      width: 100,
      render: (value: boolean | undefined) => (value === false ? <Tag color="default">Нет</Tag> : <Tag color="processing">Да</Tag>),
    },
    { title: 'Направление', dataIndex: 'direction' },
    { title: 'Организация', dataIndex: 'organization' },
    { title: 'Сотрудник', dataIndex: 'employee' },
    { title: 'Операция', dataIndex: 'operation' },
    {
      title: 'Сумма',
      dataIndex: 'total_sum',
      sorter: (a, b) => Number(a.total_sum ?? a.amount) - Number(b.total_sum ?? b.amount),
      render: (_, row) => `${Number(row.total_sum ?? row.amount).toLocaleString('ru-RU')} ${row.currency || ''}`.trim(),
    },
    {
      title: 'Счёт',
      dataIndex: 'account',
    },
    {
      title: 'Контрагент',
      dataIndex: 'counterparty',
    },
    {
      title: 'Связь с банком',
      dataIndex: 'bank_expense_id',
      render: (_, row) =>
        row.bank_expense_id ? (
          <Tag color={row.bank_expense_exists ? 'success' : 'warning'}>{`#${row.bank_expense_id}`}</Tag>
        ) : (
          <Tag>Нет</Tag>
        ),
    },
    { title: 'Комментарий', dataIndex: 'comment', render: (_, row) => row.comment || row.note || '-' },
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
          placeholder="Поиск: ID, организация, сотрудник, операция, комментарий, ID расхода банка"
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
                  <Select
                    placeholder="Операция"
                    allowClear
                    style={{ width: 220 }}
                    value={operationFilter}
                    onChange={setOperationFilter}
                    options={optionize(revenues.map((r) => r.operation || ''))}
                  />
                  <Select
                    placeholder="Контрагент"
                    allowClear
                    style={{ width: 220 }}
                    value={counterpartyFilter}
                    onChange={setCounterpartyFilter}
                    options={optionize(revenues.map((r) => r.counterparty || ''))}
                  />
                  <DatePicker.RangePicker value={dateRange} onChange={setDateRange} placeholder={['Дата от', 'Дата до']} />
                  <InputNumber placeholder="Мин. сумма" min={0} value={amountMin} onChange={setAmountMin} />
                  <InputNumber placeholder="Макс. сумма" min={0} value={amountMax} onChange={setAmountMax} />
                  <Button
                    onClick={() => {
                      setCurrencyFilter(undefined)
                      setConfirmedFilter(undefined)
                      setOperationFilter(undefined)
                      setCounterpartyFilter(undefined)
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

      {loading ? <Skeleton active style={{ marginTop: 16 }} /> : null}
      {error ? <Alert type="error" showIcon message={error} style={{ marginTop: 16, marginBottom: 16 }} /> : null}

      {!loading && !error && mode === 'all' ? (
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
          scroll={{ x: 1100 }}
        />
      ) : null}
      {!loading && !error && mode === 'expenses' ? (
        <Table<CorporateCardExpense>
          rowKey="id"
          size="small"
          columns={expenseColumns}
          dataSource={filteredExpenses}
          style={{ marginTop: 16 }}
          rowClassName={(record) => (shouldHighlightMissingRequiredRequest(record) ? 'card-row-unmatched' : '')}
          onChange={(pagination) => {
            if (pagination.current) setCurrentExpensePage(pagination.current)
            if (pagination.pageSize) setExpensePageSize(pagination.pageSize)
          }}
          pagination={{
            current: currentExpensePage,
            pageSize: expensePageSize,
            showSizeChanger: true,
            pageSizeOptions: [10, 20, 50, 100, 200],
          }}
          onRow={(record) => ({
            onClick: () => setSelectedExpense(record),
            style: { cursor: 'pointer' },
          })}
          scroll={{ x: 980 }}
        />
      ) : null}
      {!loading && !error && mode === 'revenues' ? (
        <Table<CorporateCardRevenue>
          rowKey="id"
          size="small"
          columns={revenueColumns}
          dataSource={filteredRevenues}
          style={{ marginTop: 16 }}
          onChange={(pagination) => {
            if (pagination.current) setCurrentRevenuePage(pagination.current)
            if (pagination.pageSize) setRevenuePageSize(pagination.pageSize)
          }}
          pagination={{
            current: currentRevenuePage,
            pageSize: revenuePageSize,
            showSizeChanger: true,
            pageSizeOptions: [10, 20, 50, 100, 200],
          }}
          onRow={(record) => ({
            onClick: () => setSelectedRevenue(record),
            style: { cursor: 'pointer' },
          })}
          scroll={{ x: 1800 }}
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
            <Descriptions.Item label="Дата">{formatDate(selectedRevenue.revenue_date || selectedRevenue.revenue_at)}</Descriptions.Item>
            <Descriptions.Item label="Подтверждено">
              {selectedRevenue.confirmed === false ? <Tag color="default">Нет</Tag> : <Tag color="processing">Да</Tag>}
            </Descriptions.Item>
            <Descriptions.Item label="Направление">{selectedRevenue.direction || '-'}</Descriptions.Item>
            <Descriptions.Item label="Организация">{selectedRevenue.organization || '-'}</Descriptions.Item>
            <Descriptions.Item label="Подразделение">{selectedRevenue.unit || '-'}</Descriptions.Item>
            <Descriptions.Item label="Сотрудник">{selectedRevenue.employee || '-'}</Descriptions.Item>
            <Descriptions.Item label="Тип кассы">{selectedRevenue.cash_type || '-'}</Descriptions.Item>
            <Descriptions.Item label="Операция">{selectedRevenue.operation || '-'}</Descriptions.Item>
            <Descriptions.Item label="Счёт">{selectedRevenue.account || '-'}</Descriptions.Item>
            <Descriptions.Item label="Контрагент">{selectedRevenue.counterparty || '-'}</Descriptions.Item>
            <Descriptions.Item label="Сумма">
              {`${Number(selectedRevenue.total_sum ?? selectedRevenue.amount).toLocaleString('ru-RU')} ${selectedRevenue.currency || ''}`.trim()}
            </Descriptions.Item>
            <Descriptions.Item label="Год источника">{selectedRevenue.source_year ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="ID расхода банка">{selectedRevenue.bank_expense_id ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="Связь найдена">
              {selectedRevenue.bank_expense_exists ? <Tag color="success">Да</Tag> : <Tag>Нет</Tag>}
            </Descriptions.Item>
            <Descriptions.Item label="Комментарий">{selectedRevenue.comment || selectedRevenue.note || '-'}</Descriptions.Item>
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

