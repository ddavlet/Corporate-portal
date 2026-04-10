import { useEffect, useMemo, useState } from 'react'
import { Alert, Card, DatePicker, Input, Skeleton, Space, Table, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { Dayjs } from 'dayjs'

import { getClientsDebtSnapshots, type ClientDebtSnapshot } from '../lib/api'

const moneyFmt = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })

function asMoney(value: string | number): string {
  const n = typeof value === 'number' ? value : Number(String(value).replace(',', '.'))
  return Number.isFinite(n) ? moneyFmt.format(n) : '0'
}

function dateText(value: string): string {
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '-'
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    timeZone: 'Asia/Tashkent',
  }).format(d)
}

export function ClientsDebtPage() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [rows, setRows] = useState<ClientDebtSnapshot[]>([])
  const [search, setSearch] = useState('')
  const [range, setRange] = useState<[Dayjs | null, Dayjs | null] | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setError(null)
      setLoading(true)
      try {
        const data = await getClientsDebtSnapshots()
        if (cancelled) return
        setRows(data)
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Не удалось загрузить долги клиентов')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase()
    const from = range?.[0]?.format('YYYY-MM-DD')
    const to = range?.[1]?.format('YYYY-MM-DD')
    return rows.filter((row) => {
      const dateOnly = String(row.snapshot_at || '').slice(0, 10)
      if (from && (!dateOnly || dateOnly < from)) return false
      if (to && (!dateOnly || dateOnly > to)) return false
      if (!query) return true
      const hay = `${row.client} ${row.client_id} ${row.organization} ${row.doc_type}`.toLowerCase()
      return hay.includes(query)
    })
  }, [rows, search, range])

  const columns: ColumnsType<ClientDebtSnapshot> = [
    {
      title: 'Дата',
      dataIndex: 'snapshot_at',
      width: 140,
      render: (v: string) => dateText(v),
      sorter: (a, b) => String(a.snapshot_at || '').localeCompare(String(b.snapshot_at || '')),
    },
    { title: 'Клиент', dataIndex: 'client', ellipsis: true },
    { title: 'ID клиента', dataIndex: 'client_id', width: 140 },
    { title: 'Организация', dataIndex: 'organization', width: 170, ellipsis: true },
    { title: 'Тип документа', dataIndex: 'doc_type', width: 180 },
    {
      title: 'Сумма долга',
      dataIndex: 'debt_sum',
      width: 160,
      align: 'right',
      render: (v: string | number) => asMoney(v),
      sorter: (a, b) => Number(a.debt_sum) - Number(b.debt_sum),
    },
    {
      title: 'Количество',
      dataIndex: 'quantity',
      width: 130,
      align: 'right',
      render: (v: string | number) => asMoney(v),
    },
    {
      title: 'Скидка сертификата',
      dataIndex: 'cert_discount',
      width: 180,
      align: 'right',
      render: (v: string | number) => asMoney(v),
    },
  ]

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Card>
        <Typography.Title level={4} style={{ marginTop: 0 }}>
          Долги клиентов
        </Typography.Title>
        <Space wrap>
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Поиск по клиенту / client_id / организации"
            allowClear
            style={{ width: 380 }}
          />
          <DatePicker.RangePicker value={range} onChange={(v) => setRange(v as [Dayjs | null, Dayjs | null])} />
        </Space>
      </Card>

      {error ? <Alert type="error" showIcon message={error} /> : null}
      {loading ? <Skeleton active /> : null}

      {!loading ? (
        <Card>
          <Table<ClientDebtSnapshot>
            rowKey={(r) => r.id}
            columns={columns}
            dataSource={filtered}
            size="small"
            scroll={{ x: 1200 }}
            pagination={{ pageSize: 50, showSizeChanger: true, pageSizeOptions: [20, 50, 100, 200] }}
          />
        </Card>
      ) : null}
    </Space>
  )
}

