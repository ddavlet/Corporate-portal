import { useEffect, useState } from 'react'
import { Alert, Button, Card, Descriptions, Skeleton, Space, Typography } from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import { apiFetch } from '../lib/api'
import { NoteCreateModal } from './NoteCreateModal'
import { renderExpenseRequestStatusTag } from './expenseRequestStatus'

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
  account_no: string
  mfo: string
  debit_turnover: string | number
  payment_purpose: string
  vendor?: number | null
  has_request?: boolean
  has_paid_request?: boolean
  matched_request_id?: number | null
  request_required?: boolean
}

const dateFormatterTashkent = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  timeZone: 'Asia/Tashkent',
})

const dateTimeFormatterTashkent = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  timeZone: 'Asia/Tashkent',
})

function formatDate(value?: string | null): string {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '-'
  return dateFormatterTashkent.format(parsed)
}

function formatDateTime(value?: string | null): string {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '-'
  return dateTimeFormatterTashkent.format(parsed)
}

function formatExpenseCalendar(
  y?: number | null,
  m?: number | null,
  d?: number | null,
): string {
  if (y == null && m == null && d == null) return '-'
  return [y ?? '—', m != null ? String(m).padStart(2, '0') : '—', d != null ? String(d).padStart(2, '0') : '—'].join(
    '.',
  )
}

function getCounterparty(detail: BankExpenseDetail): string {
  return String(detail.vendor_name || '').trim()
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
              <Descriptions.Item label="PK (id)">{detail.id}</Descriptions.Item>
              <Descriptions.Item label="Создано">{formatDateTime(detail.created_at)}</Descriptions.Item>
              <Descriptions.Item label="Кем создано (user id)">
                {detail.created_by != null && detail.created_by !== undefined ? detail.created_by : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="№ строки (row_no)">
                {detail.row_no != null && detail.row_no !== undefined ? detail.row_no : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="Док. №">{detail.doc_no || '-'}</Descriptions.Item>
              <Descriptions.Item label="Контрагент">{getCounterparty(detail) || '-'}</Descriptions.Item>
              <Descriptions.Item label="ИНН">{detail.inn?.trim() || '-'}</Descriptions.Item>
              <Descriptions.Item label="Расчётный счёт">{detail.account_no || '-'}</Descriptions.Item>
              <Descriptions.Item label="МФО">{detail.mfo || '-'}</Descriptions.Item>
              <Descriptions.Item label="Сумма">{Number(detail.debit_turnover).toLocaleString('ru-RU')}</Descriptions.Item>
              <Descriptions.Item label="Назначение">{detail.payment_purpose || '-'}</Descriptions.Item>
              <Descriptions.Item label="Дата док.">{formatDate(detail.doc_date)}</Descriptions.Item>
              <Descriptions.Item label="Дата проводки">{formatDate(detail.process_date)}</Descriptions.Item>
              <Descriptions.Item label="Календарь расхода (год · мес · день)">
                {formatExpenseCalendar(detail.expense_year, detail.expense_month, detail.expense_day)}
              </Descriptions.Item>
              <Descriptions.Item label="Поставщик (vendor id)">
                {detail.vendor != null && detail.vendor !== undefined ? detail.vendor : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="Статус заявки">
                {renderExpenseRequestStatusTag(detail)}
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
