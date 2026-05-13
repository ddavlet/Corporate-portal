import { useMemo, useState } from 'react'
import {
  Button,
  DatePicker,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Skeleton,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs, { type Dayjs } from 'dayjs'

import {
  createInvestReturn,
  type InvestCompanyRow,
  type InvestReturnRow,
} from '../../lib/api'
import { KpiStrip } from './KpiStrip'
import {
  asMoney,
  asNumber,
  byCompany,
  dateText,
  inDateRange,
  makeCompanySelectOptions,
  precisionFor,
  RETURN_CURRENCY_OPTIONS,
  totalsByCurrency,
  type CompanyFilter,
} from './utils'

type Props = {
  loading: boolean
  rows: InvestReturnRow[]
  companies: InvestCompanyRow[]
  companyLabel: (id: number | null) => string
  companyFilter: CompanyFilter
  onCreated: () => Promise<void> | void
}

type FormValues = {
  company?: number | null
  date: Dayjs
  sum: number
  currency: string
  type: string
  recipient: string
  comment?: string
}

const TYPE_OPTIONS = [
  { value: 'дивиденды', label: 'Дивиденды' },
  { value: 'проценты', label: 'Проценты' },
  { value: 'доля_прибыли', label: 'Доля прибыли' },
  { value: 'тело_инвестиций', label: 'Тело инвестиций' },
]

const RECIPIENT_OPTIONS = [
  { value: 'инвестор', label: 'Инвестор' },
  { value: 'партнер', label: 'Партнер' },
]

export function ReturnsTab({ loading, rows, companies, companyLabel, companyFilter, onCreated }: Props) {
  const [form] = Form.useForm<FormValues>()
  const [open, setOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [dateRange, setDateRange] = useState<[Dayjs | null, Dayjs | null] | null>(null)
  const watchedCurrency = Form.useWatch('currency', form) || 'USD'

  const filtered = useMemo(() => {
    const byCo = byCompany(rows, companyFilter)
    const from = dateRange?.[0]?.format('YYYY-MM-DD')
    const to = dateRange?.[1]?.format('YYYY-MM-DD')
    return inDateRange(byCo, 'date', from, to)
  }, [rows, companyFilter, dateRange])

  const totals = useMemo(() => totalsByCurrency(filtered, 'sum'), [filtered])
  const confirmedTotals = useMemo(
    () => totalsByCurrency(filtered.filter((r) => r.confirmed), 'sum'),
    [filtered],
  )

  const columns: ColumnsType<InvestReturnRow> = [
    {
      title: 'Дата',
      dataIndex: 'date',
      width: 120,
      render: (v: string) => dateText(v),
      sorter: (a, b) => new Date(a.date).getTime() - new Date(b.date).getTime(),
      defaultSortOrder: 'descend',
    },
    {
      title: 'Компания',
      dataIndex: 'company',
      width: 220,
      render: (v: number | null) => companyLabel(v),
      sorter: (a, b) => companyLabel(a.company).localeCompare(companyLabel(b.company)),
    },
    {
      title: 'Сумма',
      dataIndex: 'sum',
      width: 140,
      align: 'right',
      render: (v: string | number) => asMoney(v),
      sorter: (a, b) => asNumber(a.sum) - asNumber(b.sum),
    },
    {
      title: 'Сум (UZS)',
      dataIndex: 'sum_uzs',
      width: 130,
      align: 'right',
      render: (v: string | number | null | undefined) => (v != null && v !== '' ? asMoney(v) : '—'),
      sorter: (a, b) => asNumber(a.sum_uzs ?? 0) - asNumber(b.sum_uzs ?? 0),
    },
    {
      title: 'Курс CBU',
      dataIndex: 'cbu_usd_uzs_rate',
      width: 110,
      align: 'right',
      render: (v: string | number | null | undefined) => (v != null && v !== '' ? asMoney(v) : '—'),
    },
    {
      title: 'Валюта',
      dataIndex: 'currency',
      width: 90,
      sorter: (a, b) => a.currency.localeCompare(b.currency),
    },
    { title: 'Тип', dataIndex: 'type', width: 140 },
    { title: 'Получатель', dataIndex: 'recipient', width: 120 },
    {
      title: 'Подтв.',
      dataIndex: 'confirmed',
      width: 100,
      render: (v: boolean) => (v ? <Tag color="green">Да</Tag> : <Tag color="orange">Нет</Tag>),
      sorter: (a, b) => Number(a.confirmed) - Number(b.confirmed),
    },
    { title: 'Комментарий', dataIndex: 'comment', render: (v: string) => v || '-' },
  ]

  const openCreate = () => {
    form.resetFields()
    form.setFieldsValue({
      date: dayjs(),
      currency: 'USD',
      type: 'дивиденды',
      recipient: 'инвестор',
    })
    setOpen(true)
  }

  const submit = async () => {
    let values: FormValues
    try {
      values = await form.validateFields()
    } catch {
      return
    }
    setSubmitting(true)
    try {
      await createInvestReturn({
        company: values.company ?? null,
        date: values.date.format('YYYY-MM-DD'),
        sum: String(values.sum),
        currency: values.currency,
        type: values.type,
        recipient: values.recipient,
        comment: values.comment ?? '',
      })
      message.success('Выплата создана и отправлена на согласование')
      setOpen(false)
      await onCreated()
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Не удалось создать выплату')
    } finally {
      setSubmitting(false)
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
        <Button type="primary" onClick={openCreate}>
          Создать выплату
        </Button>
      </Space>

      <KpiStrip
        totals={totals}
        totalsLabel="Всего выплат"
        extra={confirmedTotals.map((t) => ({
          label: `Подтверждено, ${t.currency}`,
          value: asMoney(t.total),
        }))}
      />

      {loading ? (
        <Skeleton active />
      ) : (
        <Table
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={filtered}
          pagination={{ pageSize: 30 }}
          scroll={{ x: 1480 }}
          locale={{
            emptyText: (
              <Empty description="Выплат пока нет" image={Empty.PRESENTED_IMAGE_SIMPLE}>
                <Button type="primary" onClick={openCreate}>
                  Создать первую выплату
                </Button>
              </Empty>
            ),
          }}
        />
      )}

      <Modal
        open={open}
        title="Создать выплату"
        okText="Создать"
        cancelText="Отмена"
        confirmLoading={submitting}
        onOk={submit}
        onCancel={() => setOpen(false)}
        destroyOnClose
        width={620}
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item label="Компания" name="company">
            <Select allowClear options={makeCompanySelectOptions(companies)} placeholder="Без компании" />
          </Form.Item>
          <Space style={{ width: '100%' }} align="start" wrap>
            <Form.Item label="Дата" name="date" rules={[{ required: true, message: 'Укажите дату' }]}>
              <DatePicker format="DD.MM.YYYY" />
            </Form.Item>
            <Form.Item
              label={watchedCurrency === 'UZS' ? 'Сумма (UZS)' : 'Сумма (USD)'}
              name="sum"
              rules={[{ required: true, message: 'Укажите сумму' }]}
            >
              <InputNumber min={0} precision={precisionFor(watchedCurrency)} style={{ width: 180 }} />
            </Form.Item>
            <Form.Item label="Валюта" name="currency" rules={[{ required: true }]}>
              <Select style={{ width: 120 }} options={RETURN_CURRENCY_OPTIONS} />
            </Form.Item>
          </Space>
          <Space style={{ width: '100%' }} align="start" wrap>
            <Form.Item label="Тип" name="type" rules={[{ required: true }]}>
              <Select style={{ width: 200 }} options={TYPE_OPTIONS} />
            </Form.Item>
            <Form.Item label="Получатель" name="recipient" rules={[{ required: true }]}>
              <Select style={{ width: 180 }} options={RECIPIENT_OPTIONS} />
            </Form.Item>
          </Space>
          <Form.Item label="Комментарий" name="comment">
            <Input.TextArea rows={3} maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  )
}
