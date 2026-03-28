import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Input, Skeleton, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useNavigate } from 'react-router-dom'
import { FileAddOutlined } from '@ant-design/icons'
import { apiFetch } from '../../lib/api'

type RequestRow = {
  id: number
  title: string
  amount: number
  currency: string
  status: string
  urgency: string
  payment_type: string
  billing_date: string
}

function normalizeRows(payload: unknown): RequestRow[] {
  if (Array.isArray(payload)) return payload as RequestRow[]
  if (payload && typeof payload === 'object' && 'results' in payload) {
    const results = (payload as { results?: unknown }).results
    return Array.isArray(results) ? (results as RequestRow[]) : []
  }
  return []
}

const dateFormatter = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  timeZone: 'Asia/Tashkent',
})

function formatDate(value?: string | null): string {
  if (!value) return '-'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '-'
  return dateFormatter.format(d)
}

export function TgRequestsPage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [rows, setRows] = useState<RequestRow[]>([])
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setError(null)
      setLoading(true)
      try {
        const res = await apiFetch('/api/requests/')
        const json = await res.json().catch(() => null)
        if (!res.ok) {
          throw new Error(typeof json === 'object' && json ? JSON.stringify(json) : `HTTP ${res.status}`)
        }
        if (!cancelled) setRows(normalizeRows(json))
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Ошибка загрузки')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return rows
    return rows.filter((r) => `${r.title} ${r.status} ${r.payment_type}`.toLowerCase().includes(q))
  }, [rows, search])

  const columns: ColumnsType<RequestRow> = [
    { title: 'ID', dataIndex: 'id', width: 72 },
    { title: 'Название', dataIndex: 'title', ellipsis: true },
    {
      title: 'Сумма',
      dataIndex: 'amount',
      width: 120,
      render: (_, r) => `${Number(r.amount).toLocaleString('ru-RU')} ${r.currency || ''}`.trim(),
    },
    {
      title: 'Статус',
      dataIndex: 'status',
      width: 100,
      render: (v: string) => <Tag>{v}</Tag>,
    },
    { title: 'Биллинг', dataIndex: 'billing_date', width: 110, render: (v: string) => formatDate(v) },
  ]

  return (
    <Card styles={{ body: { padding: 12 } }}>
      <Space direction="vertical" size="middle" style={{ display: 'flex' }}>
        <Space align="center" style={{ justifyContent: 'space-between', width: '100%', flexWrap: 'wrap' }}>
          <Typography.Title level={5} style={{ margin: 0 }}>
            Заявки
          </Typography.Title>
          <Button type="primary" size="small" icon={<FileAddOutlined />} onClick={() => navigate('/tg/requests/new')}>
            Новая
          </Button>
        </Space>
        <Input placeholder="Поиск по названию, статусу, типу оплаты" value={search} onChange={(e) => setSearch(e.target.value)} allowClear />
        {error ? <Alert type="error" showIcon message={error} /> : null}
        {loading ? <Skeleton active /> : null}
        {!loading && !error ? (
          <Table<RequestRow>
            rowKey="id"
            size="small"
            columns={columns}
            dataSource={filtered}
            pagination={{ pageSize: 15, showSizeChanger: true, pageSizeOptions: [15, 30, 50] }}
            onRow={(record) => ({
              onClick: () => navigate(`/tg/requests/${record.id}`),
              style: { cursor: 'pointer' },
            })}
          />
        ) : null}
      </Space>
    </Card>
  )
}
