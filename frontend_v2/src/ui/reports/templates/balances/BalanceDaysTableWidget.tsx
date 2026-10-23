import { Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { BalanceDay, BalanceOperation } from '../../../../lib/reportsApi'
import { formatDate } from '../../../../lib/reportsFormat'
import { balanceAmount, countLabel } from './balancesFormat'

type Props = {
  days: BalanceDay[]
  loading: boolean
}

function timeOf(operation: BalanceOperation): string {
  return operation.at ? operation.at.slice(11, 16) : ''
}

/** Income in green, expense in red; «—» (nothing that day) stays neutral. */
function toned(value: string, type: 'success' | 'danger', dashForZero = false) {
  const text = balanceAmount(value, dashForZero)
  return text === '—' ? text : <Typography.Text type={type}>{text}</Typography.Text>
}

const OPERATION_COLUMNS: ColumnsType<BalanceOperation> = [
  { title: 'Время', key: 'time', width: 70, render: (_, op) => timeOf(op) || '—' },
  {
    title: 'Операция',
    key: 'title',
    render: (_, op) => (
      <>
        {op.title || '—'}
        {op.counted ? null : (
          <Tag color="warning" style={{ marginLeft: 8 }}>
            не подтверждена
          </Tag>
        )}
      </>
    ),
  },
  { title: 'Контрагент', dataIndex: 'counterparty', key: 'counterparty', render: (value: string) => value || '—' },
  { title: 'Документ', dataIndex: 'document', key: 'document', width: 110, render: (value: string) => value || '—' },
  {
    title: 'Приход',
    key: 'in',
    align: 'right',
    width: 150,
    render: (_, op) => (op.direction === 'in' ? toned(op.amount, 'success') : '—'),
  },
  {
    title: 'Расход',
    key: 'out',
    align: 'right',
    width: 150,
    render: (_, op) => (op.direction === 'out' ? toned(op.amount, 'danger') : '—'),
  },
  {
    title: 'Остаток после',
    key: 'balance',
    align: 'right',
    width: 170,
    render: (_, op) => (op.balance_after === null ? '—' : balanceAmount(op.balance_after)),
  },
]

const DAY_COLUMNS: ColumnsType<BalanceDay> = [
  {
    title: 'Дата',
    key: 'date',
    width: 170,
    render: (_, day) => (
      <>
        <span>{formatDate(day.date)}</span>{' '}
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          · {countLabel(day.operations.length)}
        </Typography.Text>
      </>
    ),
  },
  { title: 'На начало дня', key: 'opening', align: 'right', render: (_, day) => balanceAmount(day.opening) },
  {
    title: 'Приход',
    key: 'income',
    align: 'right',
    render: (_, day) => toned(day.income, 'success', true),
  },
  {
    title: 'Расход',
    key: 'expense',
    align: 'right',
    render: (_, day) => toned(day.expense, 'danger', true),
  },
  {
    title: 'На конец дня',
    key: 'closing',
    align: 'right',
    render: (_, day) => <Typography.Text strong>{balanceAmount(day.closing)}</Typography.Text>,
  },
]

/** One row per day with operations; a row opens into that day's operations with the balance after each one. */
export function BalanceDaysTableWidget({ days, loading }: Props) {
  return (
    <Table<BalanceDay>
      rowKey="date"
      size="middle"
      loading={loading}
      columns={DAY_COLUMNS}
      dataSource={days}
      pagination={days.length > 62 ? { pageSize: 31, showSizeChanger: false } : false}
      scroll={{ x: 760 }}
      // While the first report loads the table is empty: no «нет операций» under the spinner.
      locale={{ emptyText: loading ? null : 'За период операций нет' }}
      expandable={{
        expandRowByClick: true,
        expandedRowRender: (day) => (
          <Table<BalanceOperation>
            rowKey={(op) => `${op.source}-${op.id}`}
            size="small"
            // Bank lines have only a date: the time column appears when some operation of the day has one.
            columns={day.operations.some((op) => op.at) ? OPERATION_COLUMNS : OPERATION_COLUMNS.filter((column) => column.key !== 'time')}
            dataSource={day.operations}
            pagination={false}
            scroll={{ x: 900 }}
            rowClassName={(op) => (op.counted ? '' : 'balances-uncounted')}
          />
        ),
      }}
    />
  )
}
