import { useEffect, useState } from 'react'
import { Alert, Button, Card, Descriptions, Skeleton, Space, Table, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useNavigate, useParams } from 'react-router-dom'
import { apiFetch } from '../lib/api'

type PayrollLineRow = {
  id: number
  line_no: number
  employee: string
  item: string
  description?: string | null
  sum: string | number
  days_plan: number
  days_fact: number
  period_start: string
  period_end: string
  approval: boolean
}

type PayrollDocumentDetail = {
  id: number
  doc_id: string
  created_at: string
  total_sum: string | number
  lines: PayrollLineRow[]
}

const dateFmt = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  timeZone: 'Asia/Tashkent',
})

function formatDate(value?: string | null): string {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '-'
  return dateFmt.format(parsed)
}

export function PayrollDocumentDetailPage() {
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const [detail, setDetail] = useState<PayrollDocumentDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      if (!id) {
        setError('Не указан id документа.')
        setLoading(false)
        return
      }
      setLoading(true)
      setError(null)
      try {
        const res = await apiFetch(`/api/payroll/documents/${id}/`)
        const json = (await res.json().catch(() => null)) as PayrollDocumentDetail | null
        if (!res.ok) {
          throw new Error(typeof json === 'object' && json ? JSON.stringify(json) : `HTTP ${res.status}`)
        }
        if (!cancelled) setDetail(json)
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Ошибка загрузки')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [id])

  const lineColumns: ColumnsType<PayrollLineRow> = [
    { title: '№', dataIndex: 'line_no', width: 56 },
    { title: 'Сотрудник', dataIndex: 'employee' },
    { title: 'Вид', dataIndex: 'item', width: 140 },
    { title: 'Сумма', dataIndex: 'sum', width: 130, render: (v) => Number(v).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) },
    { title: 'Дни план', dataIndex: 'days_plan', width: 88 },
    { title: 'Дни факт', dataIndex: 'days_fact', width: 88 },
    {
      title: 'Период',
      key: 'period',
      width: 200,
      render: (_, r) => `${formatDate(r.period_start)} — ${formatDate(r.period_end)}`,
    },
    {
      title: 'Подтверждено',
      dataIndex: 'approval',
      width: 120,
      render: (v: boolean) => (v ? 'Да' : 'Нет'),
    },
  ]

  return (
    <Card>
      <Space direction="vertical" size={12} style={{ display: 'flex' }}>
        <Button onClick={() => navigate('/payroll')}>Назад к списку</Button>
        {loading ? <Skeleton active /> : null}
        {error ? <Alert type="error" showIcon message={error} /> : null}
        {!loading && !error && detail ? (
          <>
            <Typography.Title level={4} style={{ marginTop: 0 }}>
              Начисление ЗП: {detail.doc_id}
            </Typography.Title>
            <Descriptions bordered size="small" column={2}>
              <Descriptions.Item label="Итого">
                {Number(detail.total_sum).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </Descriptions.Item>
              <Descriptions.Item label="Строк">{detail.lines?.length ?? 0}</Descriptions.Item>
              <Descriptions.Item label="Создан">{formatDate(detail.created_at)}</Descriptions.Item>
            </Descriptions>
            <Typography.Title level={5}>Строки</Typography.Title>
            <Table<PayrollLineRow>
              rowKey="id"
              size="small"
              columns={lineColumns}
              dataSource={detail.lines || []}
              pagination={false}
            />
          </>
        ) : null}
      </Space>
    </Card>
  )
}
