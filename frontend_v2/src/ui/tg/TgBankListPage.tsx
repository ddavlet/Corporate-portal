import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Input, Skeleton, Tag, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import { ArrowLeftOutlined, SearchOutlined } from '@ant-design/icons'
import { apiFetch, getBankRevenues, type BankRevenue } from '../../lib/api'
import { tgHaptic } from './tgHaptic'

export type TgBankListMode = 'all' | 'expenses' | 'revenues'

type BankExpenseRow = {
  id: number
  row_no?: number | null
  doc_date: string
  process_date: string
  doc_no: string
  account_name?: string
  vendor_name?: string | null
  inn?: string | null
  account_no?: string
  mfo?: string
  debit_turnover: string | number
  payment_purpose: string
  has_paid_request?: boolean
  matched_request_id?: number | null
  request_required?: boolean
}

function normalizeExpenses(payload: unknown): BankExpenseRow[] {
  if (Array.isArray(payload)) return payload as BankExpenseRow[]
  if (payload && typeof payload === 'object' && 'results' in payload) {
    const results = (payload as { results?: unknown }).results
    return Array.isArray(results) ? (results as BankExpenseRow[]) : []
  }
  return []
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

function formatAmount(value: string | number | undefined): string {
  const num = Number(value ?? 0)
  return Number.isFinite(num) ? num.toLocaleString('ru-RU') : '0'
}

const TITLES: Record<TgBankListMode, string> = {
  all: 'Банк — все операции',
  expenses: 'Банк — расходы',
  revenues: 'Банк — доходы',
}

export function TgBankListPage({ mode }: { mode: TgBankListMode }) {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expenses, setExpenses] = useState<BankExpenseRow[]>([])
  const [revenues, setRevenues] = useState<BankRevenue[]>([])
  const [search, setSearch] = useState('')

  const needExpenses = mode !== 'revenues'
  const needRevenues = mode !== 'expenses'

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setError(null)
      setLoading(true)
      try {
        const [expensesRes, revenueRows] = await Promise.all([
          needExpenses ? apiFetch('/api/bank/expenses/') : Promise.resolve(null),
          needRevenues ? getBankRevenues() : Promise.resolve([] as BankRevenue[]),
        ])
        if (cancelled) return
        if (expensesRes) {
          const expensesJson = await expensesRes.json().catch(() => null)
          if (!expensesRes.ok) {
            throw new Error(
              typeof expensesJson === 'object' && expensesJson
                ? JSON.stringify(expensesJson)
                : `HTTP ${expensesRes.status}`,
            )
          }
          setExpenses(normalizeExpenses(expensesJson))
        } else {
          setExpenses([])
        }
        setRevenues(revenueRows)
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Ошибка загрузки')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [needExpenses, needRevenues])

  const expensesView = useMemo(() => {
    const q = search.trim().toLowerCase()
    const sorted = [...expenses].sort((a, b) =>
      String(b.doc_date || '').localeCompare(String(a.doc_date || '')),
    )
    if (!q) return sorted
    return sorted.filter((row) => JSON.stringify(row).toLowerCase().includes(q))
  }, [expenses, search])

  const revenuesView = useMemo(() => {
    const q = search.trim().toLowerCase()
    const sorted = [...revenues].sort((a, b) =>
      String(b.doc_date || b.created_at || '').localeCompare(String(a.doc_date || a.created_at || '')),
    )
    if (!q) return sorted
    return sorted.filter((row) => JSON.stringify(row).toLowerCase().includes(q))
  }, [revenues, search])

  const isEmpty =
    !loading &&
    !error &&
    (mode === 'all'
      ? expensesView.length === 0 && revenuesView.length === 0
      : mode === 'expenses'
        ? expensesView.length === 0
        : revenuesView.length === 0)

  return (
    <div className="tg-bank-page">
      <Button
        icon={<ArrowLeftOutlined />}
        size="large"
        onClick={() => { tgHaptic.tap(); navigate('/tg/bank') }}
        style={{ marginBottom: 12, borderRadius: 12 }}
      >
        Назад
      </Button>

      <Typography.Title level={4} style={{ margin: '0 0 16px', fontWeight: 700 }}>
        {TITLES[mode]}
      </Typography.Title>

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

      {isEmpty ? (
        <Typography.Paragraph type="secondary" style={{ textAlign: 'center', padding: '24px 8px' }}>
          Записей не найдено.
        </Typography.Paragraph>
      ) : null}

      {!loading && !error && needExpenses
        ? expensesView.map((row) => (
            <button
              key={`exp-${row.id}`}
              type="button"
              className="tg-request-row"
              onClick={() => { tgHaptic.tap(); navigate(`/tg/bank/expenses/${row.id}`) }}
            >
              <div className="tg-request-row-title">
                {mode === 'all' ? '↑ ' : ''}
                {row.vendor_name?.trim() || row.payment_purpose || `Платёж #${row.id}`}
              </div>
              <div className="tg-request-row-meta">
                <span className="tg-request-row-amount">{formatAmount(row.debit_turnover)}</span>
                <span>Док. №{row.doc_no || '—'}</span>
                <span>{formatDate(row.doc_date)}</span>
                {row.matched_request_id ? <Tag color="blue">Заявка #{row.matched_request_id}</Tag> : null}
              </div>
            </button>
          ))
        : null}

      {!loading && !error && needRevenues
        ? revenuesView.map((row) => (
            <div key={`rev-${row.id}`} className="tg-request-row" style={{ cursor: 'default' }}>
              <div className="tg-request-row-title">
                {mode === 'all' ? '↓ ' : ''}
                {row.account_name?.trim() || row.payment_purpose || `Поступление #${row.id}`}
              </div>
              <div className="tg-request-row-meta">
                <span className="tg-request-row-amount">{formatAmount(row.kredit_turnover)}</span>
                <span>Док. №{row.doc_no || '—'}</span>
                <span>{formatDate(row.doc_date)}</span>
                {row.inn ? <span>ИНН {row.inn}</span> : null}
              </div>
            </div>
          ))
        : null}
    </div>
  )
}
