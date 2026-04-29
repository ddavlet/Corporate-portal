import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, DatePicker, Form, Input, InputNumber, Select, Skeleton, Space, Table, Tabs, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'

import {
  createInvestReturn,
  createInvestPayoutScheduleShareLink,
  deleteInvestPayoutScheduleShareLink,
  getInvestCompanies,
  getInvestPayoutSchedule,
  getInvestPayoutScheduleShareLinks,
  getInvestReturns,
  getProjectInvestments,
  type InvestCompanyRow,
  type InvestPayoutScheduleRow,
  type InvestPayoutScheduleShareLinkRow,
  type InvestReturnRow,
  type ProjectInvestmentRow,
} from '../lib/api'

type CompanyFilter = 'all' | 'none' | number
type SchedulePaidFilter = 'all' | 'paid' | 'unpaid'

const moneyFmt = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })

function asMoney(value: string | number): string {
  const n = typeof value === 'number' ? value : Number(String(value).replace(',', '.'))
  return Number.isFinite(n) ? moneyFmt.format(n) : '0'
}

function asNumber(value: string | number): number {
  const n = typeof value === 'number' ? value : Number(String(value).replace(',', '.'))
  return Number.isFinite(n) ? n : 0
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
  const [returnForm] = Form.useForm()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [companyFilter, setCompanyFilter] = useState<CompanyFilter>('all')
  const [schedulePaidFilter, setSchedulePaidFilter] = useState<SchedulePaidFilter>('all')
  const [companies, setCompanies] = useState<InvestCompanyRow[]>([])
  const [investments, setInvestments] = useState<ProjectInvestmentRow[]>([])
  const [schedule, setSchedule] = useState<InvestPayoutScheduleRow[]>([])
  const [returns, setReturns] = useState<InvestReturnRow[]>([])
  const [shareLinks, setShareLinks] = useState<InvestPayoutScheduleShareLinkRow[]>([])
  const [creatingShareLink, setCreatingShareLink] = useState(false)
  const [creatingReturn, setCreatingReturn] = useState(false)
  const [deletingShareLinkId, setDeletingShareLinkId] = useState<number | null>(null)

  const loadAll = async () => {
    setLoading(true)
    setError(null)
    try {
      const [c, i, s, r, links] = await Promise.all([
        getInvestCompanies(),
        getProjectInvestments(),
        getInvestPayoutSchedule(),
        getInvestReturns(),
        getInvestPayoutScheduleShareLinks(),
      ])
      setCompanies(c)
      setInvestments(i)
      setSchedule(s)
      setReturns(r)
      setShareLinks(links)
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
  const scheduleRows = useMemo(() => {
    const byCompanyRows = byCompany(schedule, companyFilter)
    if (schedulePaidFilter === 'all') return byCompanyRows
    if (schedulePaidFilter === 'paid') return byCompanyRows.filter((r) => r.is_paid)
    return byCompanyRows.filter((r) => !r.is_paid)
  }, [schedule, companyFilter, schedulePaidFilter])
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
    { title: 'ID', dataIndex: 'id', width: 80, sorter: (a, b) => a.id - b.id },
    {
      title: 'Дата',
      dataIndex: 'payout_date',
      width: 120,
      render: (v: string) => dateText(v),
      sorter: (a, b) => new Date(a.payout_date).getTime() - new Date(b.payout_date).getTime(),
    },
    { title: 'Компания', dataIndex: 'company', width: 220, render: (v: number | null) => companyLabel(v) },
    {
      title: 'Сумма',
      dataIndex: 'amount',
      width: 140,
      align: 'right',
      render: (v: string | number) => asMoney(v),
      sorter: (a, b) => asNumber(a.amount) - asNumber(b.amount),
    },
    {
      title: 'Оплачено',
      dataIndex: 'is_paid',
      width: 110,
      render: (v: boolean) => (v ? 'Да' : 'Нет'),
      sorter: (a, b) => Number(a.is_paid) - Number(b.is_paid),
    },
    {
      title: 'Оплаченная сумма',
      dataIndex: 'payment_amount',
      width: 140,
      align: 'right',
      render: (v: string | number) => asMoney(v),
      sorter: (a, b) => asNumber(a.payment_amount) - asNumber(b.payment_amount),
    },
    { title: 'Комментарий/Назначение', dataIndex: 'comment', render: (v: string) => v || '-' },
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

  const shareLinkRows = useMemo(() => {
    return shareLinks.map((link) => ({
      ...link,
      url: `${window.location.origin}/app/public/investments/schedule/${encodeURIComponent(link.token)}`,
    }))
  }, [shareLinks])

  const shareLinkColumns: ColumnsType<(InvestPayoutScheduleShareLinkRow & { url: string })> = [
    { title: 'Создано', dataIndex: 'created_at', width: 170, render: (v: string) => dateText(v) },
    { title: 'Компания', dataIndex: 'company', width: 220, render: (v: number | null) => companyLabel(v) },
    {
      title: 'Статус',
      dataIndex: 'paid_filter',
      width: 150,
      render: (v: SchedulePaidFilter) => (v === 'paid' ? 'Оплачено' : v === 'unpaid' ? 'Не оплачено' : 'Все'),
    },
    {
      title: 'Ссылка',
      dataIndex: 'url',
      render: (v: string) => (
        <Button
          size="small"
          onClick={async () => {
            await navigator.clipboard.writeText(v)
            message.success('Ссылка скопирована')
          }}
        >
          Копировать
        </Button>
      ),
    },
    {
      title: 'Действия',
      width: 120,
      render: (_, row) => (
        <Button
          danger
          size="small"
          loading={deletingShareLinkId === row.id}
          onClick={async () => {
            try {
              setDeletingShareLinkId(row.id)
              await deleteInvestPayoutScheduleShareLink(row.id)
              setShareLinks((prev) => prev.filter((x) => x.id !== row.id))
              message.success('Ссылка удалена')
            } catch (e: unknown) {
              message.error(e instanceof Error ? e.message : 'Не удалось удалить ссылку')
            } finally {
              setDeletingShareLinkId(null)
            }
          }}
        >
          Удалить
        </Button>
      ),
    },
  ]

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Card title="Новая выплата">
        <Form
          form={returnForm}
          layout="vertical"
          initialValues={{
            currency: 'USD',
            type: 'дивиденды',
            recipient: 'инвестор',
            date: dayjs(),
          }}
          onFinish={async (values) => {
            try {
              setCreatingReturn(true)
              await createInvestReturn({
                company: values.company ?? null,
                date: values.date.format('YYYY-MM-DD'),
                sum: values.sum,
                currency: values.currency,
                type: values.type,
                recipient: values.recipient,
                comment: values.comment ?? '',
              })
              message.success('Выплата создана и отправлена на согласование')
              returnForm.resetFields(['company', 'sum', 'comment'])
              await loadAll()
            } catch (e: unknown) {
              message.error(e instanceof Error ? e.message : 'Не удалось создать выплату')
            } finally {
              setCreatingReturn(false)
            }
          }}
        >
          <Space align="start" wrap style={{ width: '100%' }}>
            <Form.Item label="Компания" name="company" style={{ minWidth: 260 }}>
              <Select
                allowClear
                options={companies.map((c) => ({ value: c.id, label: c.name }))}
                placeholder="Не выбрано (используется tenant)"
              />
            </Form.Item>
            <Form.Item label="Дата" name="date" rules={[{ required: true, message: 'Укажите дату' }]}>
              <DatePicker format="DD.MM.YYYY" />
            </Form.Item>
            <Form.Item label="Сумма" name="sum" rules={[{ required: true, message: 'Укажите сумму' }]}>
              <InputNumber min={0} precision={2} style={{ width: 180 }} />
            </Form.Item>
            <Form.Item label="Валюта" name="currency" rules={[{ required: true }]}>
              <Select
                style={{ width: 120 }}
                options={[
                  { value: 'USD', label: 'USD' },
                  { value: 'EUR', label: 'EUR' },
                  { value: 'UZS', label: 'UZS' },
                ]}
              />
            </Form.Item>
            <Form.Item label="Тип" name="type" rules={[{ required: true }]}>
              <Select
                style={{ width: 180 }}
                options={[
                  { value: 'дивиденды', label: 'Дивиденды' },
                  { value: 'проценты', label: 'Проценты' },
                  { value: 'доля_прибыли', label: 'Доля прибыли' },
                  { value: 'тело_инвестиций', label: 'Тело инвестиций' },
                ]}
              />
            </Form.Item>
            <Form.Item label="Получатель" name="recipient" rules={[{ required: true }]}>
              <Select
                style={{ width: 160 }}
                options={[
                  { value: 'инвестор', label: 'Инвестор' },
                  { value: 'партнер', label: 'Партнер' },
                ]}
              />
            </Form.Item>
          </Space>
          <Form.Item label="Комментарий" name="comment">
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={creatingReturn}>
            Создать выплату
          </Button>
        </Form>
      </Card>
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
            <Select
              style={{ minWidth: 220 }}
              options={[
                { label: 'Расписание: все', value: 'all' },
                { label: 'Расписание: оплачено', value: 'paid' },
                { label: 'Расписание: не оплачено', value: 'unpaid' },
              ]}
              value={schedulePaidFilter}
              onChange={(v) => setSchedulePaidFilter(v as SchedulePaidFilter)}
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
                  <Space direction="vertical" size="middle" style={{ width: '100%' }}>
                    <Space wrap>
                      <Button
                        type="primary"
                        loading={creatingShareLink}
                        onClick={async () => {
                          try {
                            if (companyFilter === 'none') {
                              message.error('Для фильтра "Без компании" внешняя ссылка пока не поддерживается')
                              return
                            }
                            setCreatingShareLink(true)
                            const created = await createInvestPayoutScheduleShareLink({
                              company: companyFilter === 'all' ? null : companyFilter,
                              paid_filter: schedulePaidFilter,
                            })
                            const url = `${window.location.origin}/app/public/investments/schedule/${encodeURIComponent(created.token)}`
                            setShareLinks((prev) => [created, ...prev])
                            await navigator.clipboard.writeText(url)
                            message.success('Внешняя ссылка создана и скопирована')
                          } catch (e: unknown) {
                            message.error(e instanceof Error ? e.message : 'Не удалось создать ссылку')
                          } finally {
                            setCreatingShareLink(false)
                          }
                        }}
                      >
                        Создать внешнюю ссылку по текущим фильтрам
                      </Button>
                    </Space>
                    <Table
                      rowKey="id"
                      size="small"
                      columns={scheduleColumns}
                      dataSource={scheduleRows}
                      pagination={{ pageSize: 30 }}
                      scroll={{ x: 1100 }}
                    />
                    <Typography.Title level={5} style={{ margin: 0 }}>
                      Сохранённые внешние ссылки
                    </Typography.Title>
                    <Table
                      rowKey="id"
                      size="small"
                      columns={shareLinkColumns}
                      dataSource={shareLinkRows}
                      pagination={{ pageSize: 10 }}
                      scroll={{ x: 700 }}
                    />
                  </Space>
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
