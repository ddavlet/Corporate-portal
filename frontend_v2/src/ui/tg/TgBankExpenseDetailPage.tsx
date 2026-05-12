import { useEffect, useState } from 'react'
import { Alert, Button, Skeleton, Space, Typography } from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import { apiFetch } from '../../lib/api'
import { NoteCreateModal } from '../NoteCreateModal'
import { renderExpenseRequestStatusTag } from '../expenseRequestStatus'

type BankExpenseDetail = {
  id: number
  created_at?: string
  created_by?: number | null
  row_no?: number | null
  doc_date: string
  process_date: string
  expense_year?: number | null
  expense_month?: number | null
  expense_day?: number | null
  doc_no: string
  account_name?: string
  vendor_name?: string | null
  inn?: string | null
  account_no?: string
  mfo?: string
  debit_turnover: string | number
  payment_purpose: string
  vendor?: number | null
  has_request?: boolean
  has_paid_request?: boolean
  matched_request_id?: number | null
  request_required?: boolean
}

const dateFormatter = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  timeZone: 'Asia/Tashkent',
})

const dateTimeFormatter = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  timeZone: 'Asia/Tashkent',
})

function formatDate(value?: string | null): string {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '—'
  return dateFormatter.format(d)
}

function formatDateTime(value?: string | null): string {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '—'
  return dateTimeFormatter.format(d)
}

function formatExpenseCalendar(y?: number | null, m?: number | null, d?: number | null): string {
  if (y == null && m == null && d == null) return '—'
  const year = y != null ? String(y) : '—'
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
        <Button block size="large" onClick={() => navigate('/tg/bank/expenses')} style={{ borderRadius: 12 }}>
          ← Назад к расходам
        </Button>

        {loading ? <Skeleton active /> : null}
        {error ? <Alert type="error" showIcon message={error} style={{ borderRadius: 12 }} /> : null}

        {!loading && detail ? (
          <>
            <div className="tg-detail-hero">
              <Typography.Title level={5} style={{ margin: 0, fontWeight: 700 }}>
                {detail.vendor_name?.trim() || detail.payment_purpose || `Платёж #${detail.id}`}
              </Typography.Title>
              <div className="tg-detail-amount">{Number(detail.debit_turnover).toLocaleString('ru-RU')}</div>
              <Space wrap size={[8, 8]} style={{ marginTop: 8 }}>
                {renderExpenseRequestStatusTag(detail)}
              </Space>
            </div>

            <DetailRow label="PK">{detail.id}</DetailRow>
            <DetailRow label="№ строки">{detail.row_no != null ? detail.row_no : '—'}</DetailRow>
            <DetailRow label="Док. №">{detail.doc_no || '—'}</DetailRow>
            <DetailRow label="Дата документа">{formatDate(detail.doc_date)}</DetailRow>
            <DetailRow label="Дата проводки">{formatDate(detail.process_date)}</DetailRow>
            <DetailRow label="Календарь (год · мес · день)">
              {formatExpenseCalendar(detail.expense_year, detail.expense_month, detail.expense_day)}
            </DetailRow>
            <DetailRow label="Контрагент">{detail.vendor_name?.trim() || '—'}</DetailRow>
            <DetailRow label="ИНН">{detail.inn?.trim() || '—'}</DetailRow>
            <DetailRow label="Расчётный счёт">{detail.account_no || '—'}</DetailRow>
            <DetailRow label="МФО">{detail.mfo || '—'}</DetailRow>
            <DetailRow label="Назначение платежа">{detail.payment_purpose || '—'}</DetailRow>
            <DetailRow label="Поставщик (vendor id)">
              {detail.vendor != null ? detail.vendor : '—'}
            </DetailRow>
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
        targetType="bank"
        targetId={detail?.id || null}
      />
    </div>
  )
}
