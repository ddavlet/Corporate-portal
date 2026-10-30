import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Input, Skeleton, Tag, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import { ArrowLeftOutlined, SearchOutlined } from '@ant-design/icons'
import {
  apiFetch,
  getBankAccountsOverview,
  getBankRevenues,
  type BankAccountOverviewDto,
  type BankRevenue,
} from '../../lib/api'
import { AdminEditRecordButton } from '../admin/AdminEditRecordButton'
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

/** Amount with the account currency appended for non-UZS accounts (UZS rows stay as before). */
function formatMoney(value: string | number | undefined, currency: string | null): string {
  const amount = formatAmount(value)
  return currency && currency !== 'UZS' ? `${amount} ${currency}` : amount
}

const TITLES: Record<TgBankListMode, string> = {
  all: 'Банк — все операции',
  expenses: 'Банк — расходы',
  revenues: 'Банк — доходы',
}

const ACCOUNT_MODES: { key: TgBankListMode; label: string }[] = [
  { key: 'all', label: 'Все' },
  { key: 'expenses', label: 'Расходы' },
  { key: 'revenues', label: 'Доходы' },
]

/** Header of one account's movements: name, number, currency and the «Все» / «Расходы» / «Доходы» switch. */
function TgBankAccountHeader({
  walletId,
  mode,
  account,
}: {
  walletId: number
  mode: TgBankListMode
  account: BankAccountOverviewDto | null
}) {
  const navigate = useNavigate()
  const title = account?.label?.trim() || account?.account_no || `Счёт #${walletId}`
  const details = [account?.account_no && account.account_no !== title ? account.account_no : '', account?.currency ?? '']
    .filter(Boolean)
    .join(' · ')

  return (
    <div style={{ marginBottom: 16 }}>
      <Typography.Title level={4} style={{ margin: details ? '0 0 4px' : 0, fontWeight: 700 }}>
        {title}
      </Typography.Title>
      {details ? (
        <Typography.Text type="secondary" data-testid="tg-bank-account-details">
          {details}
        </Typography.Text>
      ) : null}
      <div style={{ display: 'flex', gap: 8, marginTop: 12 }} role="group" aria-label="Раздел счёта">
        {ACCOUNT_MODES.map((item) => (
          <Button
            key={item.key}
            type={item.key === mode ? 'primary' : 'default'}
            aria-pressed={item.key === mode}
            style={{ flex: 1, borderRadius: 12 }}
            onClick={() => {
              if (item.key === mode) return
              tgHaptic.tap()
              navigate(`/tg/bank/accounts/${walletId}/${item.key}`, { replace: true })
            }}
          >
            {item.label}
          </Button>
        ))}
      </div>
    </div>
  )
}

export function TgBankListPage({ mode, walletId }: { mode: TgBankListMode; walletId?: number }) {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expenses, setExpenses] = useState<BankExpenseRow[]>([])
  const [revenues, setRevenues] = useState<BankRevenue[]>([])
  const [search, setSearch] = useState('')
  const [account, setAccount] = useState<BankAccountOverviewDto | null>(null)

  useEffect(() => {
    if (walletId === undefined) return
    let cancelled = false
    setAccount(null)
    getBankAccountsOverview()
      .then((accounts) => {
        if (!cancelled) setAccount(accounts.find((a) => a.wallet_id === walletId) ?? null)
      })
      .catch((e: unknown) => {
        // The header falls back to the wallet number; the movements below still load.
        console.warn('Bank accounts overview request failed', e)
      })
    return () => {
      cancelled = true
    }
  }, [walletId])

  const currency = walletId !== undefined ? (account?.currency ?? null) : null

  const needExpenses = mode !== 'revenues'
  const needRevenues = mode !== 'expenses'

  const loadRows = useCallback(async () => {
    setError(null)
    setLoading(true)
    try {
      const [expensesRes, revenueRows] = await Promise.all([
        needExpenses ? apiFetch(walletId !== undefined ? `/api/bank/expenses/?wallet=${walletId}` : '/api/bank/expenses/') : Promise.resolve(null),
        needRevenues ? getBankRevenues(walletId) : Promise.resolve([] as BankRevenue[]),
      ])
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
      setError(e instanceof Error ? e.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [needExpenses, needRevenues, walletId])

  useEffect(() => {
    void loadRows()
  }, [loadRows])

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

      {walletId !== undefined ? (
        <TgBankAccountHeader walletId={walletId} mode={mode} account={account} />
      ) : (
        <Typography.Title level={4} style={{ margin: '0 0 16px', fontWeight: 700 }}>
          {TITLES[mode]}
        </Typography.Title>
      )}

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
            <div key={`exp-${row.id}`} style={{ marginBottom: 10 }}>
              <button
                type="button"
                className="tg-request-row"
                style={{ marginBottom: 0 }}
                onClick={() => { tgHaptic.tap(); navigate(`/tg/bank/expenses/${row.id}`) }}
              >
                <div className="tg-request-row-title">
                  {mode === 'all' ? '↑ ' : ''}
                  {row.vendor_name?.trim() || row.payment_purpose || `Платёж #${row.id}`}
                </div>
                <div className="tg-request-row-meta">
                  <span className="tg-request-row-amount">{formatMoney(row.debit_turnover, currency)}</span>
                  <span>Док. №{row.doc_no || '—'}</span>
                  <span>{formatDate(row.doc_date)}</span>
                  {row.matched_request_id ? <Tag color="blue">Заявка #{row.matched_request_id}</Tag> : null}
                </div>
              </button>
              <AdminEditRecordButton
                endpoint="/api/bank/expenses/"
                record={row}
                onSaved={() => void loadRows()}
                block
                style={{ marginTop: 6 }}
              />
            </div>
          ))
        : null}

      {!loading && !error && needRevenues
        ? revenuesView.map((row) => (
            <div key={`rev-${row.id}`} style={{ marginBottom: 10 }}>
              <div className="tg-request-row" style={{ cursor: 'default', marginBottom: 0 }}>
                <div className="tg-request-row-title">
                  {mode === 'all' ? '↓ ' : ''}
                  {row.account_name?.trim() || row.payment_purpose || `Поступление #${row.id}`}
                </div>
                <div className="tg-request-row-meta">
                  <span className="tg-request-row-amount">{formatMoney(row.kredit_turnover, currency)}</span>
                  <span>Док. №{row.doc_no || '—'}</span>
                  <span>{formatDate(row.doc_date)}</span>
                  {row.inn ? <span>ИНН {row.inn}</span> : null}
                </div>
              </div>
              <AdminEditRecordButton
                endpoint="/api/bank/revenues/"
                record={row}
                onSaved={() => void loadRows()}
                block
                style={{ marginTop: 6 }}
              />
            </div>
          ))
        : null}
    </div>
  )
}
