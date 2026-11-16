import { useState, type ReactNode } from 'react'
import { Alert, Button, Card, Empty, Skeleton, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { ReloadOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import dayjs from 'dayjs'
import { RequestReturnBackButton } from './requests/RequestReturnBackButton'
import { BankEmployeeLinkModal, bankEmployeeLinkMode } from './payroll/BankEmployeeLinkModal'
import { fmtMoney, formatPeriodMonth } from './payroll/payrollFormat'
import { usePayrollCardAttention } from '../lib/usePayrollCardAttention'
import type {
  PayrollCardAwaitingDto,
  PayrollCardMissingDto,
  PayrollCardOverpaidDto,
  PayrollCardUnlinkedDto,
} from '../lib/payrollCardApi'

function formatDay(value: string | null | undefined): string {
  if (!value) return '—'
  const parsed = dayjs(value)
  return parsed.isValid() ? parsed.format('DD.MM.YYYY') : '—'
}

function Section<T extends object>({
  title,
  hint,
  rowKey,
  rows,
  total,
  columns,
  emptyText,
  scrollX = 'max-content',
}: {
  title: string
  hint: string
  rowKey: (row: T) => string
  rows: T[]
  /** Full size of the group; the server sends only the first rows of a long one. */
  total?: number
  columns: ColumnsType<T>
  emptyText: string
  /** A fixed width lets long bank names wrap on a desktop; narrower screens scroll the table. */
  scrollX?: number | 'max-content'
}) {
  const count = Math.max(total ?? 0, rows.length)
  return (
    <section aria-label={title}>
      <Space align="baseline" wrap size={8}>
        <Typography.Title level={5} style={{ margin: 0 }}>
          {title}
        </Typography.Title>
        {count > 0 ? <Tag color="red">{count}</Tag> : null}
      </Space>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
        {hint}
      </Typography.Paragraph>
      {count > rows.length ? (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 8 }}
          message={`Показаны первые ${rows.length} из ${count}. Разберите их и нажмите «Обновить», чтобы увидеть остальные.`}
        />
      ) : null}
      {rows.length > 0 ? (
        <Table<T>
          rowKey={rowKey}
          size="small"
          pagination={false}
          dataSource={rows}
          columns={columns}
          scroll={{ x: scrollX }}
        />
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyText} />
      )}
    </section>
  )
}

/**
 * «Выплаты на карту: разбор» — card payouts from the transit account that need a decision: payouts without an
 * employee, payouts waiting for an accrual, overpayments and expected card payouts that did not arrive.
 */
export function PayrollCardReviewPage() {
  const { data, loading, error, refresh } = usePayrollCardAttention()
  const [linkRow, setLinkRow] = useState<PayrollCardUnlinkedDto | null>(null)

  const unlinkedColumns: ColumnsType<PayrollCardUnlinkedDto> = [
    {
      title: 'В банке',
      key: 'bank_name',
      width: 260,
      render: (_, r) =>
        r.bank_full_name ? (
          r.bank_full_name
        ) : (
          <Space direction="vertical" size={0}>
            <span>{r.name_from_purpose || '—'}</span>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              из назначения, без кода сотрудника
            </Typography.Text>
          </Space>
        ),
    },
    { title: 'Карта', key: 'card', render: (_, r) => r.masked_card || r.card_account_masked },
    { title: 'Сумма', dataIndex: 'amount', align: 'right', render: (v: string) => fmtMoney(v) },
    { title: 'Дата', dataIndex: 'paid_on', render: (v: string) => formatDay(v) },
    {
      title: 'Ведомость',
      key: 'batch',
      render: (_, r) => (r.batch_num ? `№${r.batch_num} от ${formatDay(r.batch_date)}` : '—'),
    },
    { title: 'Кандидат', key: 'candidate', render: (_, r) => r.candidate?.full_name ?? '—' },
    {
      title: 'Действие',
      key: 'action',
      render: (_, r) => (
        <Button size="small" type="primary" onClick={() => setLinkRow(r)}>
          {bankEmployeeLinkMode(r) === 'link' ? 'Привязать' : 'Отнести эту выплату'}
        </Button>
      ),
    },
  ]

  const awaitingColumns: ColumnsType<PayrollCardAwaitingDto> = [
    { title: 'Сотрудник', dataIndex: 'full_name' },
    { title: 'Период', dataIndex: 'period_month', render: (v: string) => formatPeriodMonth(v) },
    { title: 'Сумма', dataIndex: 'amount', align: 'right', render: (v: string) => fmtMoney(v) },
    { title: 'Дата', dataIndex: 'paid_on', render: (v: string) => formatDay(v) },
  ]

  const overpaidColumns: ColumnsType<PayrollCardOverpaidDto> = [
    {
      title: 'Начисление',
      key: 'document',
      render: (_, r) => <Link to={`/payroll/${r.document_id}`}>{r.document_label}</Link>,
    },
    { title: 'Период', dataIndex: 'period_month', render: (v: string | null) => formatPeriodMonth(v) },
    { title: 'Сотрудник', dataIndex: 'full_name' },
    { title: 'Начислено', dataIndex: 'accrued', align: 'right', render: (v: string) => fmtMoney(v) },
    { title: 'Касса', dataIndex: 'cash', align: 'right', render: (v: string) => fmtMoney(v) },
    { title: 'Карта', dataIndex: 'card', align: 'right', render: (v: string) => fmtMoney(v) },
    {
      title: 'Переплата',
      dataIndex: 'overpaid',
      align: 'right',
      render: (v: string) => <Typography.Text type="danger">{fmtMoney(v)}</Typography.Text>,
    },
  ]

  const missingColumns: ColumnsType<PayrollCardMissingDto> = [
    {
      title: 'Начисление',
      key: 'document',
      render: (_, r) => <Link to={`/payroll/${r.document_id}`}>{r.document_label}</Link>,
    },
    { title: 'Сотрудник', dataIndex: 'full_name' },
    { title: 'Ожидалось на карту', dataIndex: 'expected', align: 'right', render: (v: string) => fmtMoney(v) },
  ]

  let body: ReactNode
  if (loading && !data) {
    body = <Skeleton active />
  } else if (error && !data) {
    body = <Alert type="error" showIcon message="Не удалось загрузить разбор выплат на карту" description={error} />
  } else if (!data) {
    // 403 and 404 both come as null: either the role is missing or the payroll module is off for the company.
    body = (
      <Alert
        type="info"
        showIcon
        message="Разбор выплат на карту недоступен: нужна роль «Начисления ЗП» и включённый модуль начислений ЗП."
      />
    )
  } else if (!data.enabled) {
    body = <Empty description="Учёт выплат на карту для компании не включён" />
  } else if (data.count === 0) {
    body = <Empty description="Всё разобрано" />
  } else {
    body = (
      <Space direction="vertical" size={24} style={{ display: 'flex' }}>
        <Section<PayrollCardUnlinkedDto>
          title="Без привязки"
          hint="Зачисления на карту, которые не отнесены к сотруднику. После привязки строка и все будущие выплаты этого сотрудника банка сами лягут на начисления."
          rowKey={(r) => `u-${r.payout_id}`}
          rows={data.unlinked}
          total={data.counts?.unlinked}
          columns={unlinkedColumns}
          emptyText="Все выплаты привязаны"
          scrollX={960}
        />
        <Section<PayrollCardAwaitingDto>
          title="Ждут начисления"
          hint="Сотрудник известен, но принятого начисления за месяц ещё нет. Выплата отнесётся сама после принятия начисления."
          rowKey={(r) => `a-${r.payout_id}`}
          rows={data.awaiting_document}
          total={data.counts?.awaiting_document}
          columns={awaitingColumns}
          emptyText="Нет выплат, ждущих начисления"
        />
        <Section<PayrollCardOverpaidDto>
          title="Переплаты"
          hint="Касса и карта вместе дали больше, чем начислено."
          rowKey={(r) => `o-${r.document_id}-${r.employee_id}`}
          rows={data.overpaid}
          total={data.counts?.overpaid}
          columns={overpaidColumns}
          emptyText="Переплат нет"
        />
        <Section<PayrollCardMissingDto>
          title="Ожидалась карта, не пришла"
          hint="В принятом начислении указана ожидаемая карта, но зачисления нет."
          rowKey={(r) => `m-${r.document_id}-${r.employee_id}`}
          rows={data.missing_card}
          total={data.counts?.missing_card}
          columns={missingColumns}
          emptyText="Все ожидаемые выплаты пришли"
        />
      </Space>
    )
  }

  return (
    <Card>
      <Space direction="vertical" size={12} style={{ display: 'flex' }}>
        <RequestReturnBackButton fallbackPath="/payroll" fallbackLabel="К начислениям" />
        <Space align="center" wrap style={{ justifyContent: 'space-between', width: '100%' }}>
          <Typography.Title level={4} style={{ margin: 0 }}>
            Выплаты на карту: разбор
          </Typography.Title>
          <Button icon={<ReloadOutlined />} loading={loading && Boolean(data)} onClick={() => void refresh()}>
            Обновить
          </Button>
        </Space>
        {error && data ? (
          <Alert
            type="warning"
            showIcon
            message="Не удалось обновить разбор, показаны прежние данные"
            description={error}
          />
        ) : null}
        {body}
      </Space>
      <BankEmployeeLinkModal row={linkRow} onClose={() => setLinkRow(null)} onDone={() => void refresh()} />
    </Card>
  )
}
