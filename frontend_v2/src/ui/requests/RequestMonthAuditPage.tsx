import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, DatePicker, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs, { type Dayjs } from 'dayjs'
import { useNavigate } from 'react-router-dom'
import { getRequestAuditMonthShifts, type RequestAuditMonthShiftsRow } from '../../lib/api'

type AuditState = {
  months: { prev: string; current: string; next: string } | null
  rows: RequestAuditMonthShiftsRow[]
}

function formatMonthKey(value?: string | null): string {
  const v = String(value || '').trim()
  if (!v) return '-'
  if (/^\d{4}-\d{2}$/.test(v)) return v
  return v.slice(0, 7) || '-'
}

function formatAmount(value?: string | null): string {
  const raw = String(value || '').trim()
  const num = Number(raw)
  if (!Number.isFinite(num)) return raw || '-'
  return num.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function RequestMonthAuditPage() {
  const navigate = useNavigate()
  const [month, setMonth] = useState<Dayjs>(() => dayjs().startOf('month'))
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<AuditState>({ months: null, rows: [] })

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setError(null)
      try {
        const resp = await getRequestAuditMonthShifts(month.format('YYYY-MM'))
        if (!cancelled) setData({ months: resp.months, rows: resp.rows })
      } catch (e: any) {
        if (!cancelled) {
          setData({ months: null, rows: [] })
          setError(e?.message || 'Ошибка запроса')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [month])

  const columns: ColumnsType<RequestAuditMonthShiftsRow> = useMemo(
    () => [
      {
        title: 'Заявка',
        dataIndex: 'request_id',
        width: 96,
        render: (value: number) => (
          <Button type="link" onClick={() => navigate(`/requests/${value}`)}>
            #{value}
          </Button>
        ),
      },
      { title: 'Категория', dataIndex: 'category', width: 180, render: (v: string) => v || '—' },
      { title: 'Поставщик', dataIndex: 'vendor', width: 220, render: (v: string) => v || '—' },
      {
        title: 'Сумма',
        key: 'amount_currency',
        width: 160,
        render: (_, row) => `${formatAmount(row.amount)} ${row.currency || ''}`.trim(),
      },
      { title: 'Тип оплаты', dataIndex: 'payment_type', width: 160, render: (v: string) => v || '—' },
      { title: 'Статус', dataIndex: 'status', width: 120, render: (v: string) => v || '—' },
      {
        title: 'Месяц начисления',
        dataIndex: 'billing_month',
        width: 140,
        render: (v: string) => formatMonthKey(v),
      },
      {
        title: 'Месяц расхода',
        dataIndex: 'expense_month',
        width: 140,
        render: (v: string) => formatMonthKey(v),
      },
      {
        title: 'Сдвиг',
        dataIndex: 'is_month_shifted',
        width: 96,
        render: (v: boolean) => (v ? <Tag color="warning">Да</Tag> : '—'),
      },
      {
        title: 'Аморт., мес',
        dataIndex: 'amortization_months',
        width: 110,
        render: (v: number) => (Number(v) > 1 ? <Tag color="processing">{v}</Tag> : '—'),
      },
      {
        title: 'Аморт. (пред.)',
        dataIndex: 'amort_prev',
        width: 120,
        render: (v: string | null | undefined) => (v ? formatAmount(v) : '—'),
      },
      {
        title: 'Аморт. (тек.)',
        dataIndex: 'amort_current',
        width: 120,
        render: (v: string | null | undefined) => (v ? formatAmount(v) : '—'),
      },
      {
        title: 'Аморт. (след.)',
        dataIndex: 'amort_next',
        width: 120,
        render: (v: string | null | undefined) => (v ? formatAmount(v) : '—'),
      },
    ],
    [navigate],
  )

  const summary = data.months
    ? `Окно: ${data.months.prev} ← ${data.months.current} → ${data.months.next}`
    : 'Окно: —'

  return (
    <Card>
      <Space align="center" style={{ justifyContent: 'space-between', width: '100%', flexWrap: 'wrap' }}>
        <Space direction="vertical" size={0}>
          <Typography.Title level={4} style={{ marginTop: 0, marginBottom: 0 }}>
            Аудит переносов и амортизации (по заявкам)
          </Typography.Title>
          <Typography.Text type="secondary">{summary}</Typography.Text>
        </Space>
        <Space wrap>
          <DatePicker
            picker="month"
            format="YYYY-MM"
            value={month}
            onChange={(value) => value && setMonth(value.startOf('month'))}
            inputReadOnly
          />
          <Button onClick={() => navigate('/requests')}>К списку заявок</Button>
        </Space>
      </Space>

      {error ? <Alert type="error" showIcon message={error} style={{ marginTop: 16 }} /> : null}

      <Table<RequestAuditMonthShiftsRow>
        style={{ marginTop: 16 }}
        rowKey="request_id"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={data.rows}
        pagination={{ pageSize: 50, showSizeChanger: true, pageSizeOptions: [20, 50, 100, 200] }}
        scroll={{ x: 1400 }}
      />
    </Card>
  )
}

