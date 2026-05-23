import { useEffect, useState } from 'react'
import { Alert, Button, Card, Descriptions, Skeleton, Space, Tag, Typography } from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import { requestReturnState } from '../lib/requestNavigation'
import { RequestReturnBackButton } from './requests/RequestReturnBackButton'
import { apiFetch } from '../lib/api'
import { NoteCreateModal } from './NoteCreateModal'
import { renderExpenseRequestStatusTag } from './expenseRequestStatus'

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
  payload?: unknown
  vendor?: number | null
  has_request?: boolean
  has_paid_request?: boolean
  matched_request_id?: number | null
  request_required?: boolean
  created_at: string
  created_by?: number | null
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

function formatPayload(payload: unknown): string {
  if (payload == null || payload === '') return '-'
  if (typeof payload === 'string') return payload || '-'
  try {
    return JSON.stringify(payload, null, 2)
  } catch {
    return String(payload)
  }
}

function formatExpenseCalendar(y: number, m: number, d: number): string {
  if (!Number.isFinite(y) && !Number.isFinite(m) && !Number.isFinite(d)) return '-'
  return [
    Number.isFinite(y) ? String(y) : '—',
    Number.isFinite(m) ? String(m).padStart(2, '0') : '—',
    Number.isFinite(d) ? String(d).padStart(2, '0') : '—',
  ].join('.')
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
          <RequestReturnBackButton fallbackPath="/cash" fallbackLabel="Назад к списку" />
          {detail?.id ? <Button onClick={() => setOpenNoteModal(true)}>Добавить заметку</Button> : null}
          {detail?.matched_request_id ? (
            <Button
              type="primary"
              onClick={() =>
                navigate(`/requests/${detail.matched_request_id}`, {
                  state: requestReturnState({
                    pathname: `/cash/${detail.id}`,
                    label: `Кассовый расход #${detail.id}`,
                  }),
                })
              }
            >
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
              <Descriptions.Item label="Внешний ID (external_id)">{detail.external_id || '-'}</Descriptions.Item>
              <Descriptions.Item label="Создано">{formatDateTime(detail.created_at)}</Descriptions.Item>
              <Descriptions.Item label="Кем создано (user id)">
                {detail.created_by != null && detail.created_by !== undefined ? detail.created_by : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="Подтверждено">
                {detail.confirmed === false ? <Tag color="default">Нет</Tag> : <Tag color="processing">Да</Tag>}
              </Descriptions.Item>
              <Descriptions.Item label="Название">{detail.title || '-'}</Descriptions.Item>
              <Descriptions.Item label="Сумма">
                {`${Number(detail.amount).toLocaleString('ru-RU')} ${detail.currency || ''}`.trim()}
              </Descriptions.Item>
              <Descriptions.Item label="Дата/время расхода">{formatDateTime(detail.expense_at)}</Descriptions.Item>
              <Descriptions.Item label="Календарь расхода (год · мес · день)">
                {formatExpenseCalendar(detail.expense_year, detail.expense_month, detail.expense_day)}
              </Descriptions.Item>
              <Descriptions.Item label="Поставщик (vendor id)">
                {detail.vendor != null && detail.vendor !== undefined ? detail.vendor : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="Статус заявки">
                {renderExpenseRequestStatusTag(detail)}
              </Descriptions.Item>
              <Descriptions.Item label="Примечание">{detail.note || '-'}</Descriptions.Item>
              <Descriptions.Item label="Payload (сырые данные)">
                <Typography.Paragraph
                  copyable={formatPayload(detail.payload) !== '-'}
                  style={{ marginBottom: 0, whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: 12 }}
                >
                  {formatPayload(detail.payload)}
                </Typography.Paragraph>
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
        targetType="cash"
        targetId={detail?.id || null}
      />
    </Card>
  )
}
