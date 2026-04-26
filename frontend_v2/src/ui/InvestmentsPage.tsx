import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Select, Skeleton, Space, Table, Tabs, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'

import {
  getInvestCompanies,
  getInvestPayoutSchedule,
  getInvestReturns,
  getProjectInvestments,
  type InvestCompanyRow,
  type InvestPayoutScheduleRow,
  type InvestReturnRow,
  type ProjectInvestmentRow,
} from '../lib/api'

type CompanyFilter = 'all' | 'none' | number

const moneyFmt = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })

function asMoney(value: string | number): string {
  const n = typeof value === 'number' ? value : Number(String(value).replace(',', '.'))
  return Number.isFinite(n) ? moneyFmt.format(n) : '0'
}

function dateText(value: string): string {
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value || '-'
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    timeZone: 'Asia/Tashkent',
  }).format(d)
}

function byCompany<T extends { company: number | null }>(rows: T[], filter: CompanyFilter): T[] {
  if (filter === 'all') return rows
  if (filter === 'none') return rows.filter((r) => r.company == null)
  return rows.filter((r) => r.company === filter)
}

export function InvestmentsPage() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [companyFilter, setCompanyFilter] = useState<CompanyFilter>('all')
  const [companies, setCompanies] = useState<InvestCompanyRow[]>([])
  const [investments, setInvestments] = useState<ProjectInvestmentRow[]>([])
  const [schedule, setSchedule] = useState<InvestPayoutScheduleRow[]>([])
  const [returns, setReturns] = useState<InvestReturnRow[]>([])

  const loadAll = async () => {
    setLoading(true)
    setError(null)
    try {
      const [c, i, s, r] = await Promise.all([
        getInvestCompanies(),
        getProjectInvestments(),
        getInvestPayoutSchedule(),
        getInvestReturns(),
      ])
      setCompanies(c)
      setInvestments(i)
      setSchedule(s)
      setReturns(r)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Не удалось загрузить данные по инвестициям')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadAll()
  }, [])

  const companyMap = useMemo(() => {
    return new Map(companies.map((c) => [c.id, c.name]))
  }, [companies])

  const companyLabel = (id: number | null) => {
    if (id == null) return 'Без компании'
    return companyMap.get(id) || `#${id}`
  }

  const investmentsRows = useMemo(() => byCompany(investments, companyFilter), [investments, companyFilter])
  const scheduleRows = useMemo(() => byCompany(schedule, companyFilter), [schedule, companyFilter])
  const returnsRows = useMemo(() => byCompany(returns, companyFilter), [returns, companyFilter])

  const companyOptions = [
    { label: 'Все компании', value: 'all' },
    { label: 'Без компании', value: 'none' },
    ...companies.map((c) => ({ label: c.name, value: c.id })),
  ]

  const companyColumns: ColumnsType<InvestCompanyRow> = [
    { title: 'ID', dataIndex: 'id', width: 80 },
    { title: 'Компания', dataIndex: 'name' },
    { title: 'Комментарий', dataIndex: 'comment', render: (v: string) => v || '-' },
    { title: 'Активна', dataIndex: 'is_active', width: 110, render: (v: boolean) => (v ? 'Да' : 'Нет') },
  ]

  const investmentsColumns: ColumnsType<ProjectInvestmentRow> = [
    { title: 'Дата', dataIndex: 'date', width: 120, render: (v: string) => dateText(v) },
    { title: 'Компания', dataIndex: 'company', width: 220, render: (v: number | null) => companyLabel(v) },
    { title: 'Сумма', dataIndex: 'amount', width: 160, align: 'right', render: (v: string | number) => asMoney(v) },
    { title: 'Валюта', dataIndex: 'currency', width: 90 },
    { title: 'Комментарий', dataIndex: 'comment', render: (v: string) => v || '-' },
  ]

  const scheduleColumns: ColumnsType<InvestPayoutScheduleRow> = [
    { title: 'Дата', dataIndex: 'payout_date', width: 120, render: (v: string) => dateText(v) },
    { title: 'Компания', dataIndex: 'company', width: 220, render: (v: number | null) => companyLabel(v) },
    { title: 'План', dataIndex: 'amount', width: 140, align: 'right', render: (v: string | number) => asMoney(v) },
    {
      title: 'Оплачено',
      dataIndex: 'payment_amount',
      width: 140,
      align: 'right',
      render: (v: string | number) => asMoney(v),
    },
    { title: 'Статус', dataIndex: 'is_paid', width: 100, render: (v: boolean) => (v ? 'Оплачено' : 'План') },
    { title: 'Валюта', dataIndex: 'currency', width: 90 },
    { title: 'Комментарий', dataIndex: 'comment', render: (v: string) => v || '-' },
  ]

  const returnsColumns: ColumnsType<InvestReturnRow> = [
    { title: 'Дата', dataIndex: 'date', width: 120, render: (v: string) => dateText(v) },
    { title: 'Компания', dataIndex: 'company', width: 220, render: (v: number | null) => companyLabel(v) },
    { title: 'Сумма', dataIndex: 'sum', width: 140, align: 'right', render: (v: string | number) => asMoney(v) },
    { title: 'Валюта', dataIndex: 'currency', width: 90 },
    { title: 'Тип', dataIndex: 'type', width: 140 },
    { title: 'Получатель', dataIndex: 'recipient', width: 120 },
    { title: 'Подтв.', dataIndex: 'confirmed', width: 90, render: (v: boolean) => (v ? 'Да' : 'Нет') },
    { title: 'Комментарий', dataIndex: 'comment', render: (v: string) => v || '-' },
  ]

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Card>
        <Space style={{ width: '100%', justifyContent: 'space-between' }} wrap>
          <Typography.Title level={4} style={{ margin: 0 }}>
            Инвестиции
          </Typography.Title>
          <Space wrap>
            <Select
              style={{ minWidth: 260 }}
              options={companyOptions}
              value={companyFilter}
              onChange={(v) => setCompanyFilter(v as CompanyFilter)}
            />
            <Button onClick={() => void loadAll()}>Обновить</Button>
          </Space>
        </Space>
      </Card>

      {error ? <Alert type="error" showIcon message={error} /> : null}
      {loading ? <Skeleton active /> : null}

      {!loading ? (
        <Card>
          <Tabs
            items={[
              {
                key: 'companies',
                label: `Компании (${companies.length})`,
                children: <Table rowKey="id" size="small" columns={companyColumns} dataSource={companies} pagination={{ pageSize: 20 }} />,
              },
              {
                key: 'investments',
                label: `Вложения (${investmentsRows.length})`,
                children: (
                  <Table
                    rowKey="id"
                    size="small"
                    columns={investmentsColumns}
                    dataSource={investmentsRows}
                    pagination={{ pageSize: 30 }}
                    scroll={{ x: 900 }}
                  />
                ),
              },
              {
                key: 'schedule',
                label: `Расписание (${scheduleRows.length})`,
                children: (
                  <Table
                    rowKey="id"
                    size="small"
                    columns={scheduleColumns}
                    dataSource={scheduleRows}
                    pagination={{ pageSize: 30 }}
                    scroll={{ x: 1100 }}
                  />
                ),
              },
              {
                key: 'returns',
                label: `Выплаты (${returnsRows.length})`,
                children: (
                  <Table
                    rowKey="id"
                    size="small"
                    columns={returnsColumns}
                    dataSource={returnsRows}
                    pagination={{ pageSize: 30 }}
                    scroll={{ x: 1200 }}
                  />
                ),
              },
            ]}
          />
        </Card>
      ) : null}
    </Space>
  )
}
