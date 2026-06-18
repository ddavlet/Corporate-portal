import { useMemo, useState } from 'react'
import {
  Alert,
  Button,
  DatePicker,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
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
import dayjs, { type Dayjs } from 'dayjs'


import {
  createInvestPayoutSchedule,
  createInvestPayoutScheduleShareLink,
  createReturnFromPayoutSchedule,
  deleteInvestPayoutScheduleShareLink,
  markPayoutScheduleAsPaid,
  type InvestCompanyRow,
  type InvestPayoutScheduleRow,
  type InvestPayoutScheduleShareLinkRow,
} from '../../lib/api'
import { KpiStrip } from './KpiStrip'
import { AdminEditRecordButton } from '../admin/AdminEditRecordButton'
import {
  asMoney,
  asNumber,
  byCompany,
  CURRENCY_OPTIONS,
  dateText,
  generateSeriesDates,
  inDateRange,
  isoDate,
  makeCompanySelectOptions,
  precisionFor,
  totalsByCurrency,
  type CompanyFilter,
  type SchedulePaidFilter,
} from './utils'

type Props = {
  loading: boolean
  rows: InvestPayoutScheduleRow[]
  companies: InvestCompanyRow[]
  shareLinks: InvestPayoutScheduleShareLinkRow[]
  companyLabel: (id: number | null) => string
  companyFilter: CompanyFilter
  paidFilter: SchedulePaidFilter
  usesCompanies: boolean
  notifyDaysBefore: number | null
  onCreated: () => Promise<void> | void
  onShareLinkCreated: (link: InvestPayoutScheduleShareLinkRow) => void
  onShareLinkDeleted: (id: number) => void
}

const RETURN_TYPE_OPTIONS = [
  { value: 'дивиденды', label: 'Дивиденды' },
  { value: 'проценты', label: 'Проценты' },
  { value: 'доля_прибыли', label: 'Доля прибыли' },
  { value: 'тело_инвестиций', label: 'Тело инвестиций' },
]

const RECIPIENT_OPTIONS = [
  { value: 'инвестор', label: 'Инвестор' },
  { value: 'партнер', label: 'Партнер' },
]

type SingleFormValues = {
  company?: number | null
  payout_date: Dayjs
  amount: number
  currency: string
  comment?: string
  return_type?: string | null
  recipient?: string | null
}

type SeriesFormValues = {
  company?: number | null
  start: Dayjs
  day: number
  count: number
  amount: number
  currency: string
  comment?: string
  return_type?: string | null
  recipient?: string | null
}

export function ScheduleTab({
  loading,
  rows,
  companies,
  shareLinks,
  companyLabel,
  companyFilter,
  paidFilter,
  usesCompanies,
  notifyDaysBefore,
  onCreated,
  onShareLinkCreated,
  onShareLinkDeleted,
}: Props) {
  const [singleForm] = Form.useForm<SingleFormValues>()
  const [seriesForm] = Form.useForm<SeriesFormValues>()
  const [singleOpen, setSingleOpen] = useState(false)
  const [seriesOpen, setSeriesOpen] = useState(false)
  const [singleSubmitting, setSingleSubmitting] = useState(false)
  const [seriesSubmitting, setSeriesSubmitting] = useState(false)
  const [creatingShareLink, setCreatingShareLink] = useState(false)
  const [deletingShareLinkId, setDeletingShareLinkId] = useState<number | null>(null)
  const [rowActionId, setRowActionId] = useState<number | null>(null)

  const handleCreateReturn = async (scheduleId: number) => {
    setRowActionId(scheduleId)
    try {
      const res = await createReturnFromPayoutSchedule(scheduleId)
      message.success(res.detail || 'Выплата создана')
      await onCreated()
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Не удалось создать выплату')
    } finally {
      setRowActionId(null)
    }
  }

  const handleMarkPaid = async (scheduleId: number) => {
    setRowActionId(scheduleId)
    try {
      const res = await markPayoutScheduleAsPaid(scheduleId)
      message.success(res.detail || 'Отмечено как оплачено')
      await onCreated()
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Не удалось отметить как оплачено')
    } finally {
      setRowActionId(null)
    }
  }
  const [dateRange, setDateRange] = useState<[Dayjs | null, Dayjs | null] | null>(null)
  const watchedSingleCurrency = Form.useWatch('currency', singleForm) || 'USD'
  const watchedSeriesCurrency = Form.useWatch('currency', seriesForm) || 'USD'
  const watchedSeries = Form.useWatch([], seriesForm)

  const filtered = useMemo(() => {
    let r = byCompany(rows, companyFilter)
    if (paidFilter === 'paid') r = r.filter((x) => x.is_paid)
    else if (paidFilter === 'unpaid') r = r.filter((x) => !x.is_paid)
    const from = dateRange?.[0]?.format('YYYY-MM-DD')
    const to = dateRange?.[1]?.format('YYYY-MM-DD')
    return inDateRange(r, 'payout_date', from, to)
  }, [rows, companyFilter, paidFilter, dateRange])

  const totals = useMemo(() => totalsByCurrency(filtered, 'amount'), [filtered])
  const unpaidTotals = useMemo(
    () => totalsByCurrency(filtered.filter((r) => !r.is_paid), 'amount'),
    [filtered],
  )
  const nextPayout = useMemo(() => {
    const today = isoDate(new Date())
    const upcoming = filtered
      .filter((r) => !r.is_paid && (r.payout_date || '').slice(0, 10) >= today)
      .sort((a, b) => (a.payout_date || '').localeCompare(b.payout_date || ''))
    return upcoming[0]
  }, [filtered])

  const seriesPreview = useMemo(() => {
    if (!watchedSeries?.start || !watchedSeries?.day || !watchedSeries?.count) return [] as Date[]
    const start = watchedSeries.start as Dayjs
    return generateSeriesDates(start.year(), start.month(), Number(watchedSeries.day), Number(watchedSeries.count))
  }, [watchedSeries])

  // Today in Asia/Tashkent (matches the backend's notification window). Plain
  // toISOString() returns UTC, which lags by 1 day between 00:00–05:00 Tashkent.
  const today = useMemo(
    () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Tashkent' }).format(new Date()),
    [],
  )

  const columns: ColumnsType<InvestPayoutScheduleRow> = useMemo(() => {
    const companyCol = {
      title: 'Компания',
      dataIndex: 'company' as const,
      width: 220,
      render: (v: number | null) => companyLabel(v),
      sorter: (a: InvestPayoutScheduleRow, b: InvestPayoutScheduleRow) =>
        companyLabel(a.company).localeCompare(companyLabel(b.company)),
    }
    return [
    { title: 'ID', dataIndex: 'id', width: 80, sorter: (a, b) => a.id - b.id },
    {
      title: 'Дата',
      dataIndex: 'payout_date',
      width: 120,
      render: (v: string) => dateText(v),
      sorter: (a, b) => new Date(a.payout_date).getTime() - new Date(b.payout_date).getTime(),
      defaultSortOrder: 'ascend' as const,
    },
    ...(usesCompanies ? [companyCol] : []),
    {
      title: 'Сумма',
      dataIndex: 'amount',
      width: 140,
      align: 'right',
      render: (v: string | number) => asMoney(v),
      sorter: (a, b) => asNumber(a.amount) - asNumber(b.amount),
    },
    {
      title: 'Валюта',
      dataIndex: 'currency',
      width: 90,
      sorter: (a, b) => a.currency.localeCompare(b.currency),
    },
    {
      title: 'Оплачено',
      dataIndex: 'is_paid',
      width: 110,
      render: (v: boolean) => (v ? <Tag color="green">Да</Tag> : <Tag>Нет</Tag>),
      sorter: (a, b) => Number(a.is_paid) - Number(b.is_paid),
    },
    {
      title: 'Оплаченная сумма',
      dataIndex: 'payment_amount',
      width: 160,
      align: 'right',
      render: (v: string | number) => asMoney(v),
      sorter: (a, b) => asNumber(a.payment_amount) - asNumber(b.payment_amount),
    },
    { title: 'Комментарий', dataIndex: 'comment', render: (v: string) => v || '-' },
    ...(notifyDaysBefore !== null
      ? [
          {
            title: 'Уведомление',
            dataIndex: 'payout_date',
            key: 'notify_status',
            width: 140,
            render: (date: string, row: InvestPayoutScheduleRow) => {
              if (row.is_paid) return <Tag>—</Tag>
              const msLeft = new Date(date).getTime() - new Date(today).getTime()
              const daysLeft = Math.ceil(msLeft / 86400000)
              if (daysLeft < 0) return <Tag color="red">Просрочено</Tag>
              if (daysLeft <= notifyDaysBefore) {
                return (
                  <Tooltip title={`Уведомление отправляется за ${notifyDaysBefore} д. до выплаты`}>
                    <Tag color="orange">Через {daysLeft} д.</Tag>
                  </Tooltip>
                )
              }
              return <Tag color="default">Через {daysLeft} д.</Tag>
            },
          },
        ]
      : []),
    {
      title: 'Действия',
      key: 'actions',
      width: 320,
      render: (_: unknown, row: InvestPayoutScheduleRow) => {
        const editBtn = (
          <AdminEditRecordButton
            endpoint="/api/investments/payout-schedule/"
            record={row}
            onSaved={() => void onCreated()}
          />
        )
        if (row.created_return) {
          return (
            <Space size={4}>
              <Typography.Text type="secondary">Выплата #{row.created_return} создана</Typography.Text>
              {editBtn}
            </Space>
          )
        }
        if (row.is_paid)
          return (
            <Space size={4}>
              <Tag color="green">Оплачено</Tag>
              {editBtn}
            </Space>
          )
        const loading = rowActionId === row.id
        return (
          <Space size={4}>
            <Popconfirm
              title="Создать выплату по расписанию?"
              okText="Создать"
              cancelText="Отмена"
              onConfirm={() => handleCreateReturn(row.id)}
            >
              <Button size="small" type="primary" loading={loading}>
                Создать выплату
              </Button>
            </Popconfirm>
            <Popconfirm
              title="Отметить выплату как оплаченную?"
              okText="Отметить"
              cancelText="Отмена"
              onConfirm={() => handleMarkPaid(row.id)}
            >
              <Button size="small" loading={loading}>
                Оплачено
              </Button>
            </Popconfirm>
            {editBtn}
          </Space>
        )
      },
    },
    ]
  }, [usesCompanies, companyLabel, notifyDaysBefore, today, rowActionId, onCreated])

  const shareLinkRows = useMemo(
    () =>
      shareLinks.map((link) => ({
        ...link,
        url: `${window.location.origin}/app/public/investments/schedule/${encodeURIComponent(link.token)}`,
      })),
    [shareLinks],
  )

  const shareLinkColumns: ColumnsType<InvestPayoutScheduleShareLinkRow & { url: string }> = useMemo(() => {
    const base: ColumnsType<InvestPayoutScheduleShareLinkRow & { url: string }> = [
    { title: 'Создано', dataIndex: 'created_at', width: 170, render: (v: string) => dateText(v) },
    ...(usesCompanies
      ? [{ title: 'Компания', dataIndex: 'company' as const, width: 220, render: (v: number | null) => companyLabel(v) }]
      : []),
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
              onShareLinkDeleted(row.id)
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
    return base
  }, [usesCompanies, companyLabel])

  const openSingle = () => {
    singleForm.resetFields()
    singleForm.setFieldsValue({ payout_date: dayjs(), currency: 'USD' })
    setSingleOpen(true)
  }

  const openSeries = () => {
    seriesForm.resetFields()
    seriesForm.setFieldsValue({ start: dayjs().startOf('month'), currency: 'USD' })
    setSeriesOpen(true)
  }

  const submitSingle = async () => {
    let values: SingleFormValues
    try {
      values = await singleForm.validateFields()
    } catch {
      return
    }
    setSingleSubmitting(true)
    try {
      await createInvestPayoutSchedule({
        company: values.company ?? null,
        payout_date: values.payout_date.format('YYYY-MM-DD'),
        amount: String(values.amount),
        currency: values.currency,
        comment: values.comment ?? '',
        return_type: values.return_type ?? null,
        recipient: values.recipient ?? null,
      })
      message.success('Выплата добавлена')
      setSingleOpen(false)
      await onCreated()
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Не удалось создать выплату')
    } finally {
      setSingleSubmitting(false)
    }
  }

  const submitSeries = async () => {
    let values: SeriesFormValues
    try {
      values = await seriesForm.validateFields()
    } catch {
      return
    }
    const dates = generateSeriesDates(values.start.year(), values.start.month(), Number(values.day), Number(values.count))
    if (dates.length === 0) {
      message.error('Серия пуста')
      return
    }
    const seriesTag = `Серия от ${isoDate(new Date())}`
    setSeriesSubmitting(true)
    try {
      const results = await Promise.allSettled(
        dates.map((d, i) =>
          createInvestPayoutSchedule({
            company: values.company ?? null,
            payout_date: isoDate(d),
            amount: String(values.amount),
            currency: values.currency,
            comment: `${values.comment ? values.comment + ' · ' : ''}${seriesTag} (${i + 1}/${dates.length})`,
            return_type: values.return_type ?? null,
            recipient: values.recipient ?? null,
          }),
        ),
      )
      const ok = results.filter((r) => r.status === 'fulfilled').length
      const fail = results.length - ok
      if (fail === 0) {
        message.success(`Серия создана: ${ok} выплат`)
        setSeriesOpen(false)
      } else {
        message.warning(`Создано ${ok} из ${results.length}; ошибок: ${fail}`)
      }
      await onCreated()
    } finally {
      setSeriesSubmitting(false)
    }
  }

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Space style={{ width: '100%', justifyContent: 'space-between' }} wrap>
        <Space wrap>
          <DatePicker.RangePicker
            value={dateRange ?? undefined}
            onChange={(v) => setDateRange(v as [Dayjs | null, Dayjs | null] | null)}
            format="DD.MM.YYYY"
            allowClear
          />
          <Typography.Text type="secondary">Записей: {filtered.length}</Typography.Text>
        </Space>
        <Space wrap>
          <Tooltip title="Создать несколько выплат за несколько месяцев сразу">
            <Button onClick={openSeries}>Создать серию выплат</Button>
          </Tooltip>
          <Tooltip title="Создать одну выплату на конкретную дату">
            <Button type="primary" onClick={openSingle}>
              Создать выплату
            </Button>
          </Tooltip>
        </Space>
      </Space>

      <KpiStrip
        totals={totals}
        totalsLabel="Запланировано"
        extra={[
          ...unpaidTotals.map((t) => ({
            label: `К оплате, ${t.currency}`,
            value: asMoney(t.total),
          })),
          ...(nextPayout
            ? [
                {
                  label: 'Ближайшая выплата',
                  value: dateText(nextPayout.payout_date),
                  hint: `${asMoney(nextPayout.amount)} ${nextPayout.currency} · ${companyLabel(nextPayout.company)}`,
                },
              ]
            : []),
        ]}
      />

      <Space wrap>
        <Button
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
                paid_filter: paidFilter,
              })
              const url = `${window.location.origin}/app/public/investments/schedule/${encodeURIComponent(created.token)}`
              onShareLinkCreated(created)
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

      {loading ? (
        <Skeleton active />
      ) : (
        <Table
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={filtered}
          pagination={{ pageSize: 30 }}
          scroll={{ x: 1100 }}
          locale={{
            emptyText: (
              <Empty description="Расписание пусто" image={Empty.PRESENTED_IMAGE_SIMPLE}>
                <Space>
                  <Tooltip title="Создать несколько выплат за несколько месяцев сразу">
                    <Button onClick={openSeries}>Создать серию</Button>
                  </Tooltip>
                  <Tooltip title="Создать одну выплату на конкретную дату">
                    <Button type="primary" onClick={openSingle}>
                      Создать выплату
                    </Button>
                  </Tooltip>
                </Space>
              </Empty>
            ),
          }}
        />
      )}

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

      <Modal
        open={singleOpen}
        title="Создать выплату"
        okText="Создать"
        cancelText="Отмена"
        confirmLoading={singleSubmitting}
        onOk={submitSingle}
        onCancel={() => setSingleOpen(false)}
        destroyOnClose
        width={560}
      >
        <Form form={singleForm} layout="vertical" preserve={false}>
          {usesCompanies ? (
            <Form.Item label="Компания" name="company">
              <Select allowClear options={makeCompanySelectOptions(companies)} placeholder="Без компании" />
            </Form.Item>
          ) : null}
          <Space style={{ width: '100%' }} align="start" wrap>
            <Form.Item
              label="Дата"
              name="payout_date"
              rules={[{ required: true, message: 'Укажите дату' }]}
            >
              <DatePicker format="DD.MM.YYYY" />
            </Form.Item>
            <Form.Item
              label="Сумма"
              name="amount"
              rules={[{ required: true, message: 'Укажите сумму' }]}
            >
              <InputNumber min={0} precision={precisionFor(watchedSingleCurrency)} style={{ width: 180 }} />
            </Form.Item>
            <Form.Item label="Валюта" name="currency" rules={[{ required: true }]}>
              <Select style={{ width: 120 }} options={CURRENCY_OPTIONS} />
            </Form.Item>
          </Space>
          <Space style={{ width: '100%' }} align="start" wrap>
            <Form.Item label="Тип выплаты" name="return_type">
              <Select allowClear style={{ width: 180 }} options={RETURN_TYPE_OPTIONS} placeholder="Не указан" />
            </Form.Item>
            <Form.Item label="Получатель" name="recipient">
              <Select allowClear style={{ width: 140 }} options={RECIPIENT_OPTIONS} placeholder="Не указан" />
            </Form.Item>
          </Space>
          <Form.Item label="Комментарий" name="comment">
            <Input.TextArea rows={3} maxLength={1000} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={seriesOpen}
        title="Создать серию выплат"
        okText="Создать серию"
        cancelText="Отмена"
        confirmLoading={seriesSubmitting}
        onOk={submitSeries}
        onCancel={() => setSeriesOpen(false)}
        destroyOnClose
        width={620}
      >
        <Form form={seriesForm} layout="vertical" preserve={false}>
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            message="Сгенерируется N выплат подряд"
            description="Если выбран день 29–31, в коротких месяцах будет использован последний день месяца."
          />
          {usesCompanies ? (
            <Form.Item label="Компания" name="company">
              <Select allowClear options={makeCompanySelectOptions(companies)} placeholder="Без компании" />
            </Form.Item>
          ) : null}
          <Space style={{ width: '100%' }} align="start" wrap>
            <Form.Item
              label="Старт (месяц)"
              name="start"
              rules={[{ required: true, message: 'Укажите месяц старта' }]}
            >
              <DatePicker picker="month" format="MM.YYYY" />
            </Form.Item>
            <Form.Item
              label="День месяца"
              name="day"
              rules={[{ required: true, message: 'Укажите день' }]}
            >
              <InputNumber min={1} max={31} style={{ width: 110 }} />
            </Form.Item>
            <Form.Item
              label="Кол-во месяцев"
              name="count"
              rules={[{ required: true, message: 'Укажите кол-во' }]}
            >
              <InputNumber min={1} max={120} style={{ width: 130 }} />
            </Form.Item>
          </Space>
          <Space style={{ width: '100%' }} align="start" wrap>
            <Form.Item
              label="Сумма каждой выплаты"
              name="amount"
              rules={[{ required: true, message: 'Укажите сумму' }]}
            >
              <InputNumber min={0} precision={precisionFor(watchedSeriesCurrency)} style={{ width: 200 }} />
            </Form.Item>
            <Form.Item label="Валюта" name="currency" rules={[{ required: true }]}>
              <Select style={{ width: 120 }} options={CURRENCY_OPTIONS} />
            </Form.Item>
          </Space>
          <Space style={{ width: '100%' }} align="start" wrap>
            <Form.Item label="Тип выплаты" name="return_type">
              <Select allowClear style={{ width: 180 }} options={RETURN_TYPE_OPTIONS} placeholder="Не указан" />
            </Form.Item>
            <Form.Item label="Получатель" name="recipient">
              <Select allowClear style={{ width: 140 }} options={RECIPIENT_OPTIONS} placeholder="Не указан" />
            </Form.Item>
          </Space>
          <Form.Item label="Комментарий" name="comment">
            <Input.TextArea rows={2} maxLength={500} placeholder="Будет добавлен к каждой записи" />
          </Form.Item>
          {seriesPreview.length > 0 ? (
            <div>
              <Typography.Text type="secondary">
                Будет создано {seriesPreview.length} выплат:
              </Typography.Text>
              <div style={{ marginTop: 6, maxHeight: 120, overflowY: 'auto', fontSize: 12 }}>
                {seriesPreview.map((d, i) => (
                  <span key={i} style={{ display: 'inline-block', marginRight: 8 }}>
                    {dateText(isoDate(d))}
                  </span>
                ))}
              </div>
            </div>
          ) : null}
        </Form>
      </Modal>
    </Space>
  )
}
