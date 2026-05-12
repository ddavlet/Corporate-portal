import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Input, Skeleton, Tag, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import { ArrowLeftOutlined, SearchOutlined } from '@ant-design/icons'
import { apiFetch, getCashRegisters, getCashRevenues, type CashRevenue } from '../../lib/api'

export type TgCashListMode = 'all' | 'expenses' | 'revenues'

type CashExpenseRow = {
  id: number
  external_id?: string
  confirmed?: boolean
  title: string
  amount: string | number
  currency: string
  expense_at: string | null
  note?: string
  has_paid_request?: boolean
  matched_request_id?: number | null
  request_required?: boolean
  wallet_id?: number | null
}

function normalizeExpenses(payload: unknown): CashExpenseRow[] {
  if (Array.isArray(payload)) return payload as CashExpenseRow[]
  if (payload && typeof payload === 'object' && 'results' in payload) {
    const results = (payload as { results?: unknown }).results
    return Array.isArray(results) ? (results as CashExpenseRow[]) : []
  }
  return []
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

function formatAmount(amount: string | number | undefined, currency?: string): string {
  const num = Number(amount ?? 0)
  const formatted = Number.isFinite(num) ? num.toLocaleString('ru-RU') : '0'
  return `${formatted} ${currency || ''}`.trim()
}

const TITLES: Record<TgCashListMode, string> = {
  all: 'Касса — все операции',
  expenses: 'Касса — расходы',
  revenues: 'Касса — доходы',
}

export function TgCashListPage({ mode }: { mode: TgCashListMode }) {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expenses, setExpenses] = useState<CashExpenseRow[]>([])
  const [revenues, setRevenues] = useState<CashRevenue[]>([])
  const [walletNameById, setWalletNameById] = useState<Record<number, string>>({})
  const [search, setSearch] = useState('')

  const needExpenses = mode !== 'revenues'
  const needRevenues = mode !== 'expenses'

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setError(null)
      setLoading(true)
      try {
        const [expensesRes, revenueRows, registers] = await Promise.all([
          needExpenses ? apiFetch('/api/cash/expenses/') : Promise.resolve(null),
          needRevenues ? getCashRevenues() : Promise.resolve([] as CashRevenue[]),
          getCashRegisters(),
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
        const byWallet: Record<number, string> = {}
        for (const reg of registers) byWallet[reg.wallet_id] = reg.name || `Касса #${reg.id}`
        setWalletNameById(byWallet)
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

  const walletLabel = (walletId?: number | null): string => {
    if (walletId == null) return '—'
    return walletNameById[walletId] || `Кошелёк #${walletId}`
  }

  const expensesView = useMemo(() => {
    const q = search.trim().toLowerCase()
    const sorted = [...expenses].sort((a, b) =>
      String(b.expense_at || '').localeCompare(String(a.expense_at || '')),
    )
    if (!q) return sorted
    return sorted.filter((row) => JSON.stringify(row).toLowerCase().includes(q))
  }, [expenses, search])

  const revenuesView = useMemo(() => {
    const q = search.trim().toLowerCase()
    const sorted = [...revenues].sort((a, b) =>
      String(b.revenue_at || b.created_at || '').localeCompare(String(a.revenue_at || a.created_at || '')),
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
    <div className="tg-cash-page">
      <Button
        icon={<ArrowLeftOutlined />}
        size="large"
        onClick={() => navigate('/tg/cash')}
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
              onClick={() => navigate(`/tg/cash/expenses/${row.id}`)}
            >
              <div className="tg-request-row-title">
                {mode === 'all' ? '↑ ' : ''}
                {row.title || `Расход #${row.id}`}
              </div>
              <div className="tg-request-row-meta">
                <span className="tg-request-row-amount">{formatAmount(row.amount, row.currency)}</span>
                {row.confirmed === false ? (
                  <Tag color="default">Не подтверждено</Tag>
                ) : (
                  <Tag color="processing">Подтверждено</Tag>
                )}
                <span>{walletLabel(row.wallet_id)}</span>
                <span>{formatDateTime(row.expense_at)}</span>
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
                {row.operation || `Доход #${row.id}`}
              </div>
              <div className="tg-request-row-meta">
                <span className="tg-request-row-amount">{formatAmount(row.total_sum, row.currency)}</span>
                {row.confirmed === false ? (
                  <Tag color="default">Не подтверждено</Tag>
                ) : (
                  <Tag color="processing">Подтверждено</Tag>
                )}
                <span>{walletLabel(row.wallet_id)}</span>
                <span>{formatDateTime(row.revenue_at || row.created_at)}</span>
                {row.counterparty ? <span>{row.counterparty}</span> : null}
              </div>
            </div>
          ))
        : null}
    </div>
  )
}
