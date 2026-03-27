import { useEffect, useState } from 'react'
import { Alert, Button, Card, Descriptions, Skeleton, Space, Tag, Typography } from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import { apiFetch } from '../lib/api'
import { NoteCreateModal } from './NoteCreateModal'

type BankExpenseDetail = {
  id: number
  row_no?: number | null
  doc_date: string
  process_date: string
  doc_no: string
  account_name: string
  inn?: string | null
  account_no: string
  mfo: string
  debit_turnover: string | number
  payment_purpose: string
  has_request?: boolean
  has_paid_request?: boolean
  matched_request_id?: number | null
}

const dateFormatterTashkent = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  timeZone: 'Asia/Tashkent',
})

function formatDate(value?: string | null): string {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '-'
  return dateFormatterTashkent.format(parsed)
}

export function BankExpenseDetailPage() {
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const [detail, setDetail] = useState<BankExpenseDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [openNoteModal, setOpenNoteModal] = useState(false)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      if (!id) {
        setError('Bank expense id is missing.')
        setLoading(false)
        return
      }
      setLoading(true)
      setError(null)
      try {
        const res = await apiFetch(`/api/bank/expenses/${id}/`)
        const json = (await res.json().catch(() => null)) as BankExpenseDetail | null
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
          <Button onClick={() => navigate('/bank')}>Назад к списку</Button>
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
              <Descriptions.Item label="Док. №">{detail.doc_no || '-'}</Descriptions.Item>
              <Descriptions.Item label="Контрагент">{detail.account_name || '-'}</Descriptions.Item>
              <Descriptions.Item label="Сумма">{Number(detail.debit_turnover).toLocaleString('ru-RU')}</Descriptions.Item>
              <Descriptions.Item label="Назначение">{detail.payment_purpose || '-'}</Descriptions.Item>
              <Descriptions.Item label="Дата док.">{formatDate(detail.doc_date)}</Descriptions.Item>
              <Descriptions.Item label="Дата проводки">{formatDate(detail.process_date)}</Descriptions.Item>
              <Descriptions.Item label="Связь с PAYED">
                {detail.has_paid_request === false ? <Tag color="gold">Без PAYED request</Tag> : <Tag color="success">OK</Tag>}
              </Descriptions.Item>
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
        targetType="bank"
        targetId={detail?.id || null}
      />
    </Card>
  )
}
