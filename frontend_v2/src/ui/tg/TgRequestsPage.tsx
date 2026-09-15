import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Input, Skeleton, Tag, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import { CalendarOutlined, FileAddOutlined, SearchOutlined } from '@ant-design/icons'
import { apiFetch } from '../../lib/api'
import { isPayedMissingLinkedExpense, type RequestExpenseLink } from '../../lib/requestExpense'
import { RequestAiChatButton } from '../requests/RequestAiChatButton'
import { AdminEditRecordButton } from '../admin/AdminEditRecordButton'
import { tgHaptic } from './tgHaptic'

type RequestRow = {
  id: number
  title: string
  amount: number
  currency: string
  status: string
  urgency: string
  payment_type: string
  billing_date: string
  expense_link?: RequestExpenseLink
}

function normalizeRows(payload: unknown): RequestRow[] {
  if (Array.isArray(payload)) return payload as RequestRow[]
  if (payload && typeof payload === 'object' && 'results' in payload) {
    const results = (payload as { results?: unknown }).results
    return Array.isArray(results) ? (results as RequestRow[]) : []
  }
  return []
}

const dateFormatter = new Intl.DateTimeFormat('ru-RU', {
  month: 'long',
  year: 'numeric',
  timeZone: 'Asia/Tashkent',
})

function formatDate(value?: string | null): string {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '—'
  return dateFormatter.format(d)
}

function statusTone(status: string): string | undefined {
  const u = String(status || '').toUpperCase()
  if (u === 'DRAFT') return 'default'
  if (u === 'REJECTED') return 'red'
  if (u === 'APPROVED' || u === 'PAYED') return 'green'
  return 'blue'
}

export function TgRequestsPage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [rows, setRows] = useState<RequestRow[]>([])
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')

  const loadRows = useCallback(async () => {
    setError(null)
    setLoading(true)
    try {
      const res = await apiFetch('/api/requests/')
      const json = await res.json().catch(() => null)
      if (!res.ok) {
        throw new Error(typeof json === 'object' && json ? JSON.stringify(json) : `HTTP ${res.status}`)
      }
      setRows(normalizeRows(json))
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadRows()
  }, [loadRows])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return rows
    return rows.filter((r) => JSON.stringify(r).toLowerCase().includes(q))
  }, [rows, search])

  return (
    <div className="tg-requests-page">
      <Typography.Title level={4} style={{ margin: '0 0 16px', fontWeight: 700 }}>
        Заявки
      </Typography.Title>
      <div style={{ marginBottom: 12 }}>
        <RequestAiChatButton block size="large" />
      </div>
      <Button
        block
        size="large"
        icon={<CalendarOutlined />}
        style={{ marginBottom: 12, borderRadius: 12 }}
        onClick={() => { tgHaptic.tap(); navigate('/tg/investments/schedule') }}
      >
        Расписание выплат
      </Button>

      <div className="tg-list-search">
        <Input
          size="large"
          placeholder="Поиск…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          allowClear
          prefix={<SearchOutlined style={{ color: 'var(--tg-hint, #999)' }} />}
        />
      </div>

      {error ? (
        <Alert type="error" showIcon message={error} style={{ marginBottom: 12, borderRadius: 12 }} />
      ) : null}
      {loading ? <Skeleton active paragraph={{ rows: 6 }} /> : null}

      {!loading && !error && filtered.length === 0 ? (
        <Typography.Paragraph type="secondary" style={{ textAlign: 'center', padding: '24px 8px' }}>
          {rows.length === 0 ? 'Пока нет заявок.' : 'Ничего не найдено.'}
        </Typography.Paragraph>
      ) : null}

      {!loading && !error
        ? filtered.map((r) => (
            <div key={r.id} style={{ marginBottom: 10 }}>
              <button
                type="button"
                className={`tg-request-row${isPayedMissingLinkedExpense(r) ? ' tg-request-row--payed-no-expense' : ''}`}
                style={{ marginBottom: 0 }}
                onClick={() => { tgHaptic.tap(); navigate(`/tg/requests/${r.id}`) }}
              >
                <div className="tg-request-row-title">{r.title || `Заявка #${r.id}`}</div>
                <div className="tg-request-row-meta">
                  <span className="tg-request-row-amount">
                    {Number(r.amount).toLocaleString('ru-RU')} {r.currency || ''}
                  </span>
                  <Tag color={statusTone(r.status)}>{r.status}</Tag>
                  <span>{r.payment_type}</span>
                  <span>Биллинг {formatDate(r.billing_date)}</span>
                </div>
              </button>
              <AdminEditRecordButton
                endpoint="/api/requests/"
                record={r}
                onSaved={() => void loadRows()}
                block
                style={{ marginTop: 6 }}
              />
            </div>
          ))
        : null}

      <button type="button" className="tg-fab-new" onClick={() => { tgHaptic.impact(); navigate('/tg/requests/new') }}>
        <FileAddOutlined style={{ marginRight: 8 }} />
        Новая заявка
      </button>
    </div>
  )
}
