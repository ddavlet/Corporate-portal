import { useEffect, useState } from 'react'
import { Alert, Button, Skeleton, Space, Tag, Typography } from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import { apiFetch } from '../../lib/api'
import { tgHaptic } from './tgHaptic'
import { requestReturnState } from '../../lib/requestNavigation'
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
  note?: string
  matched_request_id?: number | null
  request_required?: boolean
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

  const externalNo = detail?.external_id?.trim()

  return (
    <div className="tg-detail-page">
      <Space direction="vertical" size={12} style={{ display: 'flex' }}>
        <Button block size="large" onClick={() => { tgHaptic.tap(); navigate('/tg/cash/expenses') }} style={{ borderRadius: 12 }}>
          ← Назад к расходам
        </Button>

        {loading ? <Skeleton active /> : null}
        {error ? <Alert type="error" showIcon message={error} style={{ borderRadius: 12 }} /> : null}

        {!loading && detail ? (
          <>
            <div className="tg-detail-hero">
              <Typography.Title level={5} style={{ margin: 0, fontWeight: 700 }}>
                {detail.title || `Кассовый расход #${detail.id}`}
              </Typography.Title>
              {externalNo ? (
                <Typography.Text type="secondary" style={{ display: 'block', marginTop: 4 }}>
                  № {externalNo}
                </Typography.Text>
              ) : null}
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

            <DetailRow label="Дата и время">{formatDateTime(detail.expense_at)}</DetailRow>
            <DetailRow label="Примечание">{detail.note || '—'}</DetailRow>

            <div className="tg-actions-stack" style={{ marginTop: 16 }}>
              <Button size="large" onClick={() => { tgHaptic.impact(); setOpenNoteModal(true) }}>
                Добавить заметку
              </Button>
              {detail.matched_request_id ? (
                <Button
                  type="primary"
                  size="large"
                  onClick={() => {
                    tgHaptic.tap()
                    navigate(`/tg/requests/${detail.matched_request_id}`, {
                      state: requestReturnState({
                        pathname: `/tg/cash/expenses/${detail.id}`,
                        label: `Кассовый расход #${detail.id}`,
                      }),
                    })
                  }}
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
