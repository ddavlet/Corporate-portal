import { useEffect, useMemo, useState } from 'react'
import { Alert, Card, Skeleton, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useParams } from 'react-router-dom'
import { getPublicInvestPayoutSchedule, type PublicInvestPayoutScheduleRow } from '../lib/api'

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

export function PublicInvestmentsSchedulePage() {
  const { token = '' } = useParams<{ token: string }>()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [rows, setRows] = useState<PublicInvestPayoutScheduleRow[]>([])
  const [meta, setMeta] = useState<{
    company_name: string
    tenant_name: string
    paid_filter: 'all' | 'paid' | 'unpaid'
  } | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setError(null)
      try {
        const data = await getPublicInvestPayoutSchedule(token)
        if (cancelled) return
        setRows(data.rows)
        setMeta({
          company_name: data.filters.company_name || 'Все компании',
          tenant_name: data.filters.tenant_name || '',
          paid_filter: data.filters.paid_filter,
        })
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Ошибка загрузки')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [token])

  const bigTitle = useMemo(() => {
    const companyName = String(meta?.company_name || '').trim()
    if (companyName) return companyName
    return String(meta?.tenant_name || '').trim() || '—'
  }, [meta])

  const columns: ColumnsType<PublicInvestPayoutScheduleRow> = [
    { title: 'ID', dataIndex: 'id', width: 90 },
    { title: 'Дата', dataIndex: 'payout_date', width: 130, render: (v: string) => dateText(v) },
    { title: 'Компания', dataIndex: 'company_name', width: 240, render: (v: string) => v || 'Без компании' },
    { title: 'Сумма', dataIndex: 'amount', width: 150, align: 'right', render: (v: string | number) => asMoney(v) },
    {
      title: 'Оплачено',
      dataIndex: 'is_paid',
      width: 120,
      render: (v: boolean) => <Tag color={v ? 'green' : 'orange'}>{v ? 'Да' : 'Нет'}</Tag>,
    },
    { title: 'Оплаченная сумма', dataIndex: 'payment_amount', width: 170, align: 'right', render: (v) => asMoney(v) },
    { title: 'Комментарий/Назначение', dataIndex: 'comment', render: (v: string) => v || '-' },
  ]

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%', padding: 16 }}>
      <Card>
        <Typography.Title level={2} style={{ margin: 0 }}>
          {bigTitle}
        </Typography.Title>
        <Typography.Title level={4} style={{ margin: '8px 0 0' }}>
          График выплат
        </Typography.Title>
      </Card>

      {error ? <Alert type="error" showIcon message={error} /> : null}
      {loading ? <Skeleton active /> : null}

      {!loading && !error ? (
        <Card>
          <Table rowKey="id" size="small" columns={columns} dataSource={rows} pagination={{ pageSize: 30 }} scroll={{ x: 1150 }} />
        </Card>
      ) : null}
    </Space>
  )
}
