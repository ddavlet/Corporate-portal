import { useEffect, useState } from 'react'
import { Alert, Button, Skeleton, Space, Typography } from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import { apiFetch } from '../../lib/api'
import { tgHaptic } from './tgHaptic'
import { requestReturnState } from '../../lib/requestNavigation'
import { NoteCreateModal } from '../NoteCreateModal'
import { renderExpenseRequestStatusTag } from '../expenseRequestStatus'

type BankExpenseDetail = {
  id: number
  doc_date: string
  process_date: string
  doc_no: string
  vendor_name?: string | null
  inn?: string | null
  account_no?: string
  mfo?: string
  debit_turnover: string | number
  payment_purpose: string
  matched_request_id?: number | null
  request_required?: boolean
}

const dateFormatter = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  timeZone: 'Asia/Tashkent',
})

function formatDate(value?: string | null): string {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '—'
  return dateFormatter.format(d)
}

function DetailRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="tg-detail-row">
      <span className="tg-detail-label">{label}</span>
      <div className="tg-detail-value">{children}</div>
    </div>
  )
}

export function TgBankExpenseDetailPage() {
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
        setError('Не указан идентификатор платежа.')
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
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Ошибка загрузки платежа')
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
        <Button block size="large" onClick={() => { tgHaptic.tap(); navigate('/tg/bank/expenses') }} style={{ borderRadius: 12 }}>
          ← Назад к расходам
        </Button>

        {loading ? <Skeleton active /> : null}
        {error ? <Alert type="error" showIcon message={error} style={{ borderRadius: 12 }} /> : null}

        {!loading && detail ? (
          <>
            <div className="tg-detail-hero">
              <Typography.Title level={5} style={{ margin: 0, fontWeight: 700 }}>
                {detail.vendor_name?.trim() || detail.payment_purpose || `Банковский платёж #${detail.id}`}
              </Typography.Title>
              <Typography.Text type="secondary" style={{ display: 'block', marginTop: 4 }}>
                {detail.doc_no ? `Док. № ${detail.doc_no}` : `Платёж #${detail.id}`}
              </Typography.Text>
              <div className="tg-detail-amount">{Number(detail.debit_turnover).toLocaleString('ru-RU')}</div>
              <div style={{ marginTop: 8 }}>{renderExpenseRequestStatusTag(detail)}</div>
            </div>

            <DetailRow label="Дата документа">{formatDate(detail.doc_date)}</DetailRow>
            <DetailRow label="Дата проводки">{formatDate(detail.process_date)}</DetailRow>
            <DetailRow label="Контрагент">{detail.vendor_name?.trim() || '—'}</DetailRow>
            {detail.inn?.trim() ? <DetailRow label="ИНН">{detail.inn.trim()}</DetailRow> : null}
            <DetailRow label="Назначение платежа">{detail.payment_purpose || '—'}</DetailRow>

            <div className="tg-actions-stack" style={{ marginTop: 16 }}>
              <Button size="large" onClick={() => { tgHaptic.impact('light'); setOpenNoteModal(true) }}>
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
                        pathname: `/tg/bank/expenses/${detail.id}`,
                        label: `Банковский платёж #${detail.id}`,
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
        targetType="bank"
        targetId={detail?.id || null}
      />
    </div>
  )
}
