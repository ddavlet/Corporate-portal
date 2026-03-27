import { useEffect, useState } from 'react'
import { Alert, Button, Card, Descriptions, Skeleton, Space, Tag, Typography } from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import { apiFetch } from '../lib/api'
import { NoteCreateModal } from './NoteCreateModal'

type CashExpenseDetail = {
  id: number
  external_id: string
  confirmed?: boolean
  title: string
  amount: string | number
  currency: string
  expense_at: string | null
  expense_year: number
  expense_month: number
  expense_day: number
  note: string
  has_request?: boolean
  has_paid_request?: boolean
  matched_request_id?: number | null
  created_at: string
}

const dateTimeFormatterTashkent = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  timeZone: 'Asia/Tashkent',
})

function formatDateTime(value?: string | null): string {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '-'
  return dateTimeFormatterTashkent.format(parsed)
}

export function CashExpenseDetailPage() {
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const [detail, setDetail] = useState<CashExpenseDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [openNoteModal, setOpenNoteModal] = useState(false)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      if (!id) {
        setError('Cash expense id is missing.')
        setLoading(false)
        return
      }
      setLoading(true)
      setError(null)
      try {
        const res = await apiFetch(`/api/cash/expenses/${id}/`)
        const json = (await res.json().catch(() => null)) as CashExpenseDetail | null
        if (!res.ok) {
          throw new Error(typeof json === 'object' && json ? JSON.stringify(json) : `HTTP ${res.status}`)
        }
        if (!cancelled) setDetail(json)
      } catch (e: any) {
        if (!cancelled) setError(e?.message || 'Ошибка загрузки расхода')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [id])

  return (
    <Card>
      <Space direction="vertical" size={12} style={{ display: 'flex' }}>
        <Space>
          <Button onClick={() => navigate('/cash')}>Назад к списку</Button>
          {detail?.id ? <Button onClick={() => setOpenNoteModal(true)}>Добавить заметку</Button> : null}
          {detail?.matched_request_id ? (
            <Button type="primary" onClick={() => navigate(`/requests/${detail.matched_request_id}`)}>
              Открыть связанную заявку
            </Button>
          ) : null}
        </Space>
        {loading ? <Skeleton active /> : null}
        {error ? <Alert type="error" showIcon message={error} /> : null}
        {!loading && detail ? (
          <>
            <Descriptions bordered size="small" column={1}>
              <Descriptions.Item label="PK">{detail.id}</Descriptions.Item>
              <Descriptions.Item label="ID">{detail.external_id || '-'}</Descriptions.Item>
              <Descriptions.Item label="Подтверждено">
                {detail.confirmed === false ? <Tag color="default">Нет</Tag> : <Tag color="processing">Да</Tag>}
              </Descriptions.Item>
              <Descriptions.Item label="Название">{detail.title || '-'}</Descriptions.Item>
              <Descriptions.Item label="Сумма">
                {`${Number(detail.amount).toLocaleString('ru-RU')} ${detail.currency || ''}`.trim()}
              </Descriptions.Item>
              <Descriptions.Item label="Дата/время расхода">{formatDateTime(detail.expense_at)}</Descriptions.Item>
              <Descriptions.Item label="Примечание">{detail.note || '-'}</Descriptions.Item>
            </Descriptions>
            <Typography.Text type="secondary">
              {detail.matched_request_id
                ? `Связанная заявка: #${detail.matched_request_id}`
                : 'Связанная заявка не найдена'}
            </Typography.Text>
          </>
        ) : null}
      </Space>
      <NoteCreateModal
        open={openNoteModal}
        onCancel={() => setOpenNoteModal(false)}
        targetType="cash"
        targetId={detail?.id || null}
      />
    </Card>
  )
}
