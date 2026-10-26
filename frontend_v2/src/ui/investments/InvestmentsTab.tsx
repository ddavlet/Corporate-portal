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

import { useInvestmentFundingMode } from '../../lib/useInvestmentFundingMode'
import {
  createProjectInvestment,
  type InvestCompanyRow,
  type ProjectInvestmentRow,
} from '../../lib/api'
import { InvestmentRecordDetailModal } from './InvestmentRecordDetailModal'
import { InvestmentFromRequestsModal } from './InvestmentFromRequestsModal'
import { FUNDING_METHOD_LABELS, fundingMethodLabel, type FundingMethod } from './fundingPool'
import { AdminEditRecordButton } from '../admin/AdminEditRecordButton'
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
  totalsInBothCurrencies,
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
  funding_method?: FundingMethod
}

type MethodFilter = 'all' | FundingMethod | 'none'

const FUNDING_METHOD_OPTIONS = [
  { value: 'cash', label: FUNDING_METHOD_LABELS.cash },
  { value: 'bank_transfer', label: FUNDING_METHOD_LABELS.bank_transfer },
]

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
  const [selectedRow, setSelectedRow] = useState<ProjectInvestmentRow | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [dateRange, setDateRange] = useState<[Dayjs | null, Dayjs | null] | null>(null)
  const fundingMode = useInvestmentFundingMode()
  const [collectOpen, setCollectOpen] = useState(false)
  const [methodFilter, setMethodFilter] = useState<MethodFilter>('all')
  const watchedCurrency = Form.useWatch('currency', form) || 'USD'

  const filtered = useMemo(() => {
    const byCo = byCompany(rows, companyFilter)
    const from = dateRange?.[0]?.format('YYYY-MM-DD')
    const to = dateRange?.[1]?.format('YYYY-MM-DD')
    const byDate = inDateRange(byCo, 'date', from, to)
    if (methodFilter === 'all') return byDate
    if (methodFilter === 'none') return byDate.filter((r) => !r.funding_method)
    return byDate.filter((r) => r.funding_method === methodFilter)
  }, [rows, companyFilter, dateRange, methodFilter])

  // Итоги в USD и UZS (по курсу ЦБ на дату) отдельно по подтверждённым и неподтверждённым заявкам.
  const confirmedTotals = useMemo(() => totalsInBothCurrencies(filtered.filter((r) => r.confirmed)), [filtered])
  const pendingTotals = useMemo(() => totalsInBothCurrencies(filtered.filter((r) => !r.confirmed)), [filtered])
  const notConvertedCount = useMemo(
    () => filtered.filter((r) => r.sum_usd == null || r.sum_uzs == null).length,
    [filtered],
  )

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
    { title: 'ID', dataIndex: 'id', width: 80, sorter: (a, b) => a.id - b.id },
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
    {
      title: 'Способ внесения',
      dataIndex: 'funding_method',
      width: 160,
      render: (v: ProjectInvestmentRow['funding_method']) => fundingMethodLabel(v),
    },
    {
      title: 'Статус заявки',
      dataIndex: 'confirmed',
      width: 150,
      render: (v: boolean) =>
        v ? <Tag color="success">Подтверждена</Tag> : <Tag color="warning">На согласовании</Tag>,
    },
    { title: 'Комментарий', dataIndex: 'comment', render: (v: string) => v || '-' },
    {
      title: 'Действия',
      key: 'actions',
      width: 160,
      render: (_: unknown, row: ProjectInvestmentRow) => (
        <AdminEditRecordButton
          endpoint="/api/investments/project-investments/"
          record={row}
          onSaved={() => void onCreated()}
        />
      ),
    },
    ]
  }, [usesCompanies, companyLabel, onCreated])

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
        funding_method: values.funding_method,
      })
      message.success('Заявка на вложение создана')
      setOpen(false)
      await onCreated()
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Не удалось создать заявку на вложение')
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
          <Select
            value={methodFilter}
            onChange={setMethodFilter}
            style={{ width: 200 }}
            aria-label="Способ внесения"
            options={[
              { value: 'all', label: 'Все способы внесения' },
              ...FUNDING_METHOD_OPTIONS,
              { value: 'none', label: 'Способ не указан' },
            ]}
          />
          <Typography.Text type="secondary">Записей: {filtered.length}</Typography.Text>
        </Space>
        {fundingMode ? (
          <Button type="primary" onClick={() => setCollectOpen(true)}>
            Собрать по заявкам
          </Button>
        ) : (
          <Button type="primary" onClick={openCreate}>
            Подать заявку на вложение
          </Button>
        )}
      </Space>

      <KpiStrip
        totals={confirmedTotals}
        totalsLabel="Подтверждено"
        extra={[
          ...pendingTotals.map((t) => ({ label: `Не подтверждено, ${t.currency}`, value: asMoney(t.total) })),
          ...(notConvertedCount > 0
            ? [
                {
                  label: 'Не учтено в сумме',
                  value: String(notConvertedCount),
                  hint: 'Заявки в валюте без курса ЦБ (например, EUR)',
                },
              ]
            : []),
        ]}
      />

      {loading ? (
        <Skeleton active />
      ) : (
        <Table
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={filtered}
          onRow={(record) => ({
            onClick: () => setSelectedRow(record),
            style: { cursor: 'pointer' },
          })}
          pagination={{ pageSize: 30 }}
          scroll={{ x: 980 }}
          locale={{
            emptyText: (
              <Empty description="Заявок на вложение пока нет" image={Empty.PRESENTED_IMAGE_SIMPLE}>
                {fundingMode ? (
                  <Button type="primary" onClick={() => setCollectOpen(true)}>
                    Собрать по заявкам
                  </Button>
                ) : (
                  <Button type="primary" onClick={openCreate}>
                    Подать первую заявку
                  </Button>
                )}
              </Empty>
            ),
          }}
        />
      )}

      <InvestmentRecordDetailModal
        open={Boolean(selectedRow)}
        onCancel={() => setSelectedRow(null)}
        kind="project"
        record={selectedRow}
        companyLabel={companyLabel}
        usesCompanies={usesCompanies}
      />

      <InvestmentFromRequestsModal
        open={collectOpen}
        onCancel={() => setCollectOpen(false)}
        onCreated={onCreated}
        usesCompanies={usesCompanies}
        companies={companies}
      />

      <Modal
        open={open}
        title="Заявка на вложение"
        okText="Отправить"
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
              <Select
                style={{ width: 120 }}
                options={CURRENCY_OPTIONS}
                onChange={() => form.setFieldValue('amount', undefined)}
              />
            </Form.Item>
          </Space>
          <Form.Item
            label="Способ внесения"
            name="funding_method"
            rules={[{ required: true, message: 'Укажите способ внесения' }]}
          >
            <Select options={FUNDING_METHOD_OPTIONS} placeholder="Выберите способ" />
          </Form.Item>
          <Form.Item label="Комментарий" name="comment">
            <Input.TextArea rows={3} maxLength={1000} />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  )
}
