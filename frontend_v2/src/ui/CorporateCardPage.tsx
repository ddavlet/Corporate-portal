import { useEffect, useMemo, useState } from 'react'
import { Alert, Card, Descriptions, Input, Modal, Skeleton, Table, Tabs, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  getCorporateCardExpenses,
  getCorporateCardRevenues,
  type CorporateCardExpense,
  type CorporateCardRevenue,
} from '../lib/api'

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

export function CorporateCardPage() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expenses, setExpenses] = useState<CorporateCardExpense[]>([])
  const [revenues, setRevenues] = useState<CorporateCardRevenue[]>([])
  const [search, setSearch] = useState('')
  const [currentExpensePage, setCurrentExpensePage] = useState(1)
  const [expensePageSize, setExpensePageSize] = useState(10)
  const [currentRevenuePage, setCurrentRevenuePage] = useState(1)
  const [revenuePageSize, setRevenuePageSize] = useState(10)
  const [selectedExpense, setSelectedExpense] = useState<CorporateCardExpense | null>(null)
  const [selectedRevenue, setSelectedRevenue] = useState<CorporateCardRevenue | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setError(null)
      try {
        const [expenseRows, revenueRows] = await Promise.all([getCorporateCardExpenses(), getCorporateCardRevenues()])
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
  }, [])

  const normalizedSearch = search.trim().toLowerCase()

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
    if (!normalizedSearch) return allRows
    return allRows.filter((row) => {
      const haystack = `${row.kind} ${row.id} ${row.title || ''} ${row.note || ''}`.toLowerCase()
      return haystack.includes(normalizedSearch)
    })
  }, [allRows, normalizedSearch])

  const filteredExpenses = useMemo(() => {
    if (!normalizedSearch) return expenses
    return expenses.filter((row) => {
      const haystack = `${row.id} ${row.title || ''} ${row.note || ''}`.toLowerCase()
      return haystack.includes(normalizedSearch)
    })
  }, [expenses, normalizedSearch])

  const filteredRevenues = useMemo(() => {
    if (!normalizedSearch) return revenues
    return revenues.filter((row) => {
      const haystack =
        `${row.id} ${row.external_id || ''} ${row.organization || ''} ${row.employee || ''} ` +
        `${row.operation || ''} ${row.account || ''} ${row.counterparty || ''} ` +
        `${row.comment || row.note || ''} ${row.bank_expense_id ?? ''}`.toLowerCase()
      return haystack.includes(normalizedSearch)
    })
  }, [revenues, normalizedSearch])

  type AllRow = (typeof allRows)[number]
  const allColumns: ColumnsType<AllRow> = [
    {
      title: 'Тип',
      dataIndex: 'kind',
      width: 100,
      render: (value: 'expense' | 'revenue') =>
        value === 'expense' ? <Tag color="gold">Expense</Tag> : <Tag color="green">Revenue</Tag>,
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
      title: 'Дата расхода',
      dataIndex: 'expense_at',
      sorter: (a, b) => String(a.expense_at || '').localeCompare(String(b.expense_at || '')),
      render: (value: string) => formatDateTime(value),
    },
    { title: 'Примечание', dataIndex: 'note' },
  ]

  const revenueColumns: ColumnsType<CorporateCardRevenue> = [
    { title: 'ID', dataIndex: 'id', width: 90, sorter: (a, b) => a.id - b.id },
    { title: 'id', dataIndex: 'external_id', width: 120, sorter: (a, b) => String(a.external_id || '').localeCompare(String(b.external_id || '')) },
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
      title: 'Bank link',
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
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Corporate Card
      </Typography.Title>
      <Typography.Text type="secondary">Расходы и пополнения корпоративной карты</Typography.Text>

      <Input
        placeholder="Поиск: id, организация, сотрудник, операция, комментарий, bank_expense_id"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        allowClear
        style={{ width: 420, marginTop: 12, marginBottom: 12 }}
      />

      {loading ? <Skeleton active style={{ marginTop: 16 }} /> : null}
      {error ? <Alert type="error" showIcon message={error} style={{ marginTop: 16, marginBottom: 16 }} /> : null}

      {!loading && !error ? (
        <Tabs
          items={[
            {
              key: 'all',
              label: 'All',
              children: (
                <Table<AllRow>
                  rowKey={(r) => `${r.kind}:${r.id}`}
                  size="small"
                  columns={allColumns}
                  dataSource={filteredAllRows}
                  onRow={(record) => ({
                    onClick: () => {
                      if (record.kind === 'expense') setSelectedExpense(record.raw as CorporateCardExpense)
                      else setSelectedRevenue(record.raw as CorporateCardRevenue)
                    },
                    style: { cursor: 'pointer' },
                  })}
                  pagination={{ defaultPageSize: 10, showSizeChanger: true, pageSizeOptions: [10, 20, 50, 100, 200] }}
                  scroll={{ x: 1100 }}
                />
              ),
            },
            {
              key: 'expenses',
              label: 'Expenses',
              children: (
                <Table<CorporateCardExpense>
                  rowKey="id"
                  size="small"
                  columns={expenseColumns}
                  dataSource={filteredExpenses}
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
              ),
            },
            {
              key: 'revenues',
              label: 'Revenues',
              children: (
                <Table<CorporateCardRevenue>
                  rowKey="id"
                  size="small"
                  columns={revenueColumns}
                  dataSource={filteredRevenues}
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
              ),
            },
          ]}
        />
      ) : null}

      <Modal
        open={Boolean(selectedExpense)}
        title={selectedExpense ? `Card expense #${selectedExpense.id}` : 'Card expense'}
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
            <Descriptions.Item label="Создано">{formatDateTime(selectedExpense.created_at)}</Descriptions.Item>
          </Descriptions>
        ) : null}
      </Modal>

      <Modal
        open={Boolean(selectedRevenue)}
        title={selectedRevenue ? `Card revenue #${selectedRevenue.id}` : 'Card revenue'}
        footer={null}
        onCancel={() => setSelectedRevenue(null)}
      >
        {selectedRevenue ? (
          <Descriptions bordered size="small" column={1}>
            <Descriptions.Item label="ID">{selectedRevenue.id}</Descriptions.Item>
            <Descriptions.Item label="id">{selectedRevenue.external_id || '-'}</Descriptions.Item>
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
            <Descriptions.Item label="source_year">{selectedRevenue.source_year ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="bank_expense_id">{selectedRevenue.bank_expense_id ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="Связь найдена">
              {selectedRevenue.bank_expense_exists ? <Tag color="success">Да</Tag> : <Tag>Нет</Tag>}
            </Descriptions.Item>
            <Descriptions.Item label="Комментарий">{selectedRevenue.comment || selectedRevenue.note || '-'}</Descriptions.Item>
            <Descriptions.Item label="Создано">{formatDateTime(selectedRevenue.created_at)}</Descriptions.Item>
          </Descriptions>
        ) : null}
      </Modal>
    </Card>
  )
}

