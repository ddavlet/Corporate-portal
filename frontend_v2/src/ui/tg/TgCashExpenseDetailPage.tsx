import { useEffect, useState } from 'react'
import { Alert, Button, Skeleton, Space, Tag, Typography } from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import { apiFetch } from '../../lib/api'
import { NoteCreateModal } from '../NoteCreateModal'
import { renderExpenseRequestStatusTag } from '../expenseRequestStatus'

type CashExpenseDetail = {
  id: number
  external_id?: string
  confirmed?: boolean
  title?: string
  amount: string | number
  currency?: string
  expense_at: string | null
  expense_year?: number
  expense_month?: number
  expense_day?: number
  note?: string
  payload?: unknown
  vendor?: number | null
  has_request?: boolean
  has_paid_request?: boolean
  matched_request_id?: number | null
  request_required?: boolean
  created_at?: string
  created_by?: number | null
}

const dateTimeFormatter = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  timeZone: 'Asia/Tashkent',
})

function formatDateTime(value?: string | null): string {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '—'
  return dateTimeFormatter.format(d)
}

function formatExpenseCalendar(y?: number, m?: number, d?: number): string {
  if (y == null && m == null && d == null) return '—'
  const year = Number.isFinite(y) ? String(y) : '—'
  const month = m != null ? String(m).padStart(2, '0') : '—'
  const day = d != null ? String(d).padStart(2, '0') : '—'
  return [year, month, day].join('.')
}

function DetailRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="tg-detail-row">
      <span className="tg-detail-label">{label}</span>
      <div className="tg-detail-value">{children}</div>
    </div>
  )
}

export function TgCashExpenseDetailPage() {
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
        setError('Не указан идентификатор расхода.')
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
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Ошибка загрузки расхода')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [id])

  return (
    <div className="tg-detail-page">
      <Space direction="vertical" size={12} style={{ display: 'flex' }}>
        <Button block size="large" onClick={() => navigate('/tg/cash/expenses')} style={{ borderRadius: 12 }}>
          ← Назад к расходам
        </Button>

        {loading ? <Skeleton active /> : null}
        {error ? <Alert type="error" showIcon message={error} style={{ borderRadius: 12 }} /> : null}

        {!loading && detail ? (
          <>
            <div className="tg-detail-hero">
              <Typography.Title level={5} style={{ margin: 0, fontWeight: 700 }}>
                {detail.title || `Расход #${detail.id}`}
              </Typography.Title>
              <div className="tg-detail-amount">
                {Number(detail.amount).toLocaleString('ru-RU')} {detail.currency || ''}
              </div>
              <Space wrap size={[8, 8]} style={{ marginTop: 8 }}>
                {detail.confirmed === false ? (
                  <Tag color="default">Не подтверждено</Tag>
                ) : (
                  <Tag color="processing">Подтверждено</Tag>
                )}
                {renderExpenseRequestStatusTag(detail)}
              </Space>
            </div>

            <DetailRow label="PK">{detail.id}</DetailRow>
            <DetailRow label="Внешний ID">{detail.external_id || '—'}</DetailRow>
            <DetailRow label="Дата/время расхода">{formatDateTime(detail.expense_at)}</DetailRow>
            <DetailRow label="Календарь (год · мес · день)">
              {formatExpenseCalendar(detail.expense_year, detail.expense_month, detail.expense_day)}
            </DetailRow>
            <DetailRow label="Поставщик (vendor id)">
              {detail.vendor != null ? detail.vendor : '—'}
            </DetailRow>
            <DetailRow label="Примечание">{detail.note || '—'}</DetailRow>
            <DetailRow label="Создано">{formatDateTime(detail.created_at)}</DetailRow>
            <DetailRow label="Кем создано (user id)">
              {detail.created_by != null ? detail.created_by : '—'}
            </DetailRow>

            <div className="tg-actions-stack" style={{ marginTop: 16 }}>
              <Button size="large" onClick={() => setOpenNoteModal(true)}>
                Добавить заметку
              </Button>
              {detail.matched_request_id ? (
                <Button
                  type="primary"
                  size="large"
                  onClick={() => navigate(`/tg/requests/${detail.matched_request_id}`)}
                >
                  Открыть связанную заявку
                </Button>
              ) : null}
            </div>

            {!detail.matched_request_id ? (
              <Typography.Text type="secondary">Связанная заявка не найдена.</Typography.Text>
            ) : null}
          </>
        ) : null}
      </Space>

      <NoteCreateModal
        open={openNoteModal}
        onCancel={() => setOpenNoteModal(false)}
        targetType="cash"
        targetId={detail?.id || null}
      />
    </div>
  )
}
