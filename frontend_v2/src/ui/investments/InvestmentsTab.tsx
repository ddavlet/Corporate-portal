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
  Typography,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs, { type Dayjs } from 'dayjs'

import {
  createProjectInvestment,
  type InvestCompanyRow,
  type ProjectInvestmentRow,
} from '../../lib/api'
import { KpiStrip } from './KpiStrip'
import {
  asMoney,
  asNumber,
  byCompany,
  CURRENCY_OPTIONS,
  dateText,
  inDateRange,
  makeCompanySelectOptions,
  precisionFor,
  totalsByCurrency,
  type CompanyFilter,
} from './utils'

type Props = {
  loading: boolean
  rows: ProjectInvestmentRow[]
  companies: InvestCompanyRow[]
  companyLabel: (id: number | null) => string
  companyFilter: CompanyFilter
  usesCompanies: boolean
  onCreated: () => Promise<void> | void
}

type FormValues = {
  company?: number | null
  date: Dayjs
  amount: number
  currency: string
  comment?: string
}

export function InvestmentsTab({
  loading,
  rows,
  companies,
  companyLabel,
  companyFilter,
  usesCompanies,
  onCreated,
}: Props) {
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

  const totals = useMemo(() => totalsByCurrency(filtered, 'amount'), [filtered])

  const columns: ColumnsType<ProjectInvestmentRow> = useMemo(() => {
    const companyCol = {
      title: 'Компания',
      dataIndex: 'company' as const,
      width: 220,
      render: (v: number | null) => companyLabel(v),
      sorter: (a: ProjectInvestmentRow, b: ProjectInvestmentRow) =>
        companyLabel(a.company).localeCompare(companyLabel(b.company)),
    }
    return [
    {
      title: 'Дата',
      dataIndex: 'date',
      width: 120,
      render: (v: string) => dateText(v),
      sorter: (a, b) => new Date(a.date).getTime() - new Date(b.date).getTime(),
      defaultSortOrder: 'descend' as const,
    },
    ...(usesCompanies ? [companyCol] : []),
    {
      title: 'Сумма',
      dataIndex: 'amount',
      width: 160,
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
    { title: 'Комментарий', dataIndex: 'comment', render: (v: string) => v || '-' },
    ]
  }, [usesCompanies, companyLabel])

  const openCreate = () => {
    form.resetFields()
    form.setFieldsValue({ date: dayjs(), currency: 'USD' })
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
      await createProjectInvestment({
        company: values.company ?? null,
        date: values.date.format('YYYY-MM-DD'),
        amount: String(values.amount),
        currency: values.currency,
        comment: values.comment ?? '',
      })
      message.success('Вложение создано')
      setOpen(false)
      await onCreated()
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Не удалось создать вложение')
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
          Создать вложение
        </Button>
      </Space>

      <KpiStrip totals={totals} totalsLabel="Сумма вложений" />

      {loading ? (
        <Skeleton active />
      ) : (
        <Table
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={filtered}
          pagination={{ pageSize: 30 }}
          scroll={{ x: 900 }}
          locale={{
            emptyText: (
              <Empty description="Вложений нет" image={Empty.PRESENTED_IMAGE_SIMPLE}>
                <Button type="primary" onClick={openCreate}>
                  Создать первое вложение
                </Button>
              </Empty>
            ),
          }}
        />
      )}

      <Modal
        open={open}
        title="Создать вложение"
        okText="Создать"
        cancelText="Отмена"
        confirmLoading={submitting}
        onOk={submit}
        onCancel={() => setOpen(false)}
        destroyOnClose
        width={560}
      >
        <Form form={form} layout="vertical" preserve={false}>
          {usesCompanies ? (
            <Form.Item label="Компания" name="company">
              <Select allowClear options={makeCompanySelectOptions(companies)} placeholder="Без компании" />
            </Form.Item>
          ) : null}
          <Space style={{ width: '100%' }} align="start" wrap>
            <Form.Item label="Дата" name="date" rules={[{ required: true, message: 'Укажите дату' }]}>
              <DatePicker format="DD.MM.YYYY" />
            </Form.Item>
            <Form.Item
              label="Сумма"
              name="amount"
              rules={[{ required: true, message: 'Укажите сумму' }]}
            >
              <InputNumber min={0} precision={precisionFor(watchedCurrency)} style={{ width: 180 }} />
            </Form.Item>
            <Form.Item label="Валюта" name="currency" rules={[{ required: true }]}>
              <Select style={{ width: 120 }} options={CURRENCY_OPTIONS} />
            </Form.Item>
          </Space>
          <Form.Item label="Комментарий" name="comment">
            <Input.TextArea rows={3} maxLength={1000} />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  )
}
