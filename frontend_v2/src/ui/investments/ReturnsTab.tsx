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
import type { Dayjs } from 'dayjs'

import type { InvestReturnRow } from '../../lib/api'
import { isAllowedBillingMonth } from '../../lib/billingMonth'
import { InvestmentRecordDetailModal } from './InvestmentRecordDetailModal'
import { AdminEditRecordButton } from '../admin/AdminEditRecordButton'
import { CbuRateAlert } from './CbuRateAlert'
import { KpiStrip } from './KpiStrip'
import {
  INVEST_RETURN_RECIPIENT_OPTIONS,
  investReturnDefaults,
  useInvestReturnCreateForm,
  type InvestReturnFormValues,
} from './useInvestReturnCreateForm'
import {
  asMoney,
  asNumber,
  confirmedInvestorUsdTotal,
  dateText,
  inDateRange,
  precisionFor,
  RETURN_CURRENCY_OPTIONS,
  totalsInBothCurrencies,
} from './utils'

type Props = {
  loading: boolean
  rows: InvestReturnRow[]
  returnTypeSelectOptions: { value: string; label: string }[]
  onCreated: () => Promise<void> | void
}

function accrualMonthLabel(iso: string | undefined): string {
  if (!iso || iso.length < 7) return '—'
  const [y, m] = iso.slice(0, 10).split('-')
  if (!y || !m) return '—'
  return `${m}.${y}`
}

export function ReturnsTab({ loading, rows, returnTypeSelectOptions, onCreated }: Props) {
  const [form] = Form.useForm<InvestReturnFormValues>()
  const [open, setOpen] = useState(false)
  const [selectedRow, setSelectedRow] = useState<InvestReturnRow | null>(null)
  const createForm = useInvestReturnCreateForm({
    onCreated: async () => {
      setOpen(false)
      await onCreated()
    },
  })
  const [dateRange, setDateRange] = useState<[Dayjs | null, Dayjs | null] | null>(null)
  const watchedCurrency = Form.useWatch('currency', form) || 'USD'

  const filtered = useMemo(() => {
    const from = dateRange?.[0]?.format('YYYY-MM-DD')
    const to = dateRange?.[1]?.format('YYYY-MM-DD')
    return inDateRange(rows, 'date', from, to)
  }, [rows, dateRange])

  const totals = useMemo(() => totalsInBothCurrencies(filtered), [filtered])
  const confirmedTotals = useMemo(
    () => totalsInBothCurrencies(filtered.filter((r) => r.confirmed)),
    [filtered],
  )
  const investorUsdTotal = useMemo(() => confirmedInvestorUsdTotal(filtered), [filtered])

  const columns: ColumnsType<InvestReturnRow> = useMemo(() => {
    const rest: ColumnsType<InvestReturnRow> = [
    { title: 'ID', dataIndex: 'id', width: 80, sorter: (a, b) => a.id - b.id },
    {
      title: 'Дата',
      dataIndex: 'date',
      width: 120,
      render: (v: string) => dateText(v),
      sorter: (a, b) => new Date(a.date).getTime() - new Date(b.date).getTime(),
      defaultSortOrder: 'descend' as const,
    },
    {
      title: 'Месяц начисления',
      dataIndex: 'billing_date',
      width: 130,
      render: (_: unknown, row: InvestReturnRow) => accrualMonthLabel(row.billing_date),
      sorter: (a, b) =>
        String(a.billing_date || '').slice(0, 7).localeCompare(String(b.billing_date || '').slice(0, 7)),
    },
    {
      title: 'В валюте выплаты',
      dataIndex: 'sum',
      width: 150,
      align: 'right',
      render: (v: string | number) => asMoney(v),
      sorter: (a, b) => asNumber(a.sum) - asNumber(b.sum),
    },
    {
      title: 'Валюта',
      dataIndex: 'currency',
      width: 90,
      sorter: (a, b) => a.currency.localeCompare(b.currency),
    },
    {
      title: 'В сумах',
      dataIndex: 'sum_uzs',
      width: 150,
      align: 'right',
      render: (v: string | number | null | undefined) => (v != null && v !== '' ? asMoney(v) : '—'),
      sorter: (a, b) => asNumber(a.sum_uzs ?? 0) - asNumber(b.sum_uzs ?? 0),
    },
    {
      title: 'В долларах',
      dataIndex: 'sum_usd',
      width: 130,
      align: 'right',
      render: (v: string | number | null | undefined) => (v != null && v !== '' ? asMoney(v) : '—'),
      sorter: (a, b) => asNumber(a.sum_usd ?? 0) - asNumber(b.sum_usd ?? 0),
    },
    { title: 'Тип', dataIndex: 'type', width: 140 },
    { title: 'Получатель', dataIndex: 'recipient', width: 120 },
    {
      title: 'Подтверждена',
      dataIndex: 'confirmed',
      width: 120,
      render: (v: boolean) => (v ? <Tag color="green">Да</Tag> : <Tag color="orange">Нет</Tag>),
      sorter: (a, b) => Number(a.confirmed) - Number(b.confirmed),
    },
    { title: 'Комментарий', dataIndex: 'comment', render: (v: string) => v || '-' },
    {
      title: 'Действия',
      key: 'actions',
      width: 160,
      render: (_: unknown, row: InvestReturnRow) => (
        <AdminEditRecordButton endpoint="/api/investments/returns/" record={row} onSaved={() => void onCreated()} />
      ),
    },
    ]
    return rest
  }, [onCreated])

  const openCreate = () => {
    form.resetFields()
    form.setFieldsValue(investReturnDefaults(returnTypeSelectOptions))
    setOpen(true)
  }

  const submit = async () => {
    let values: InvestReturnFormValues
    try {
      values = await form.validateFields()
    } catch {
      return
    }
    const result = await createForm.submit(values)
    if (result === 'invalid_month') message.warning('Выберите допустимый месяц назначения')
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

      <CbuRateAlert rows={filtered} />

      <KpiStrip
        totals={totals}
        totalsLabel="Всего выплат"
        extra={[
          ...confirmedTotals.map((t) => ({
            label: `Подтверждено, ${t.currency}`,
            value: asMoney(t.total),
          })),
          {
            label: 'Инвестору (подтверждено), USD',
            value: asMoney(investorUsdTotal),
            hint: 'Как «Выплачено всего» в отчёте инвесторам',
          },
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
          scroll={{ x: 1870 }}
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

      <InvestmentRecordDetailModal
        open={Boolean(selectedRow)}
        onCancel={() => setSelectedRow(null)}
        kind="return"
        record={selectedRow}
      />

      <Modal
        open={open}
        title="Создать выплату"
        okText="Создать"
        cancelText="Отмена"
        confirmLoading={createForm.submitting}
        onOk={submit}
        onCancel={() => setOpen(false)}
        destroyOnClose
        width={620}
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item
            label="Месяц начисления"
            name="billing_date"
            rules={[{ required: true, message: 'Укажите месяц начисления' }]}
            extra="Доступны только месяцы, ещё не закрытые начислениями."
          >
            <DatePicker
              picker="month"
              format="MM.YYYY"
              style={{ width: 160 }}
              disabledDate={(current) => !current || !isAllowedBillingMonth(current)}
            />
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
              <Select style={{ width: 200 }} options={returnTypeSelectOptions} />
            </Form.Item>
            <Form.Item label="Получатель" name="recipient" rules={[{ required: true }]}>
              <Select style={{ width: 180 }} options={INVEST_RETURN_RECIPIENT_OPTIONS} />
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
