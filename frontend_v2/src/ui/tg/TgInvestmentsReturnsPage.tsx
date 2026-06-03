import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Input, Skeleton, Tag, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import { ArrowLeftOutlined, PlusOutlined, SearchOutlined } from '@ant-design/icons'
import { tgHaptic } from './tgHaptic'
import {
  DEFAULT_INVESTMENT_FORM_CONFIG,
  getInvestmentFormConfig,
  getInvestCompanies,
  getInvestReturns,
  type InvestCompanyRow,
  type InvestReturnRow,
} from '../../lib/api'

const dateFormatter = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  timeZone: 'Asia/Tashkent',
})

function formatDate(value: string): string {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value || '—'
  return dateFormatter.format(d)
}

function formatAmount(value: string | number | undefined, currency?: string): string {
  const num = Number(value ?? 0)
  const formatted = Number.isFinite(num) ? num.toLocaleString('ru-RU') : '0'
  return `${formatted} ${currency || ''}`.trim()
}

const TYPE_LABEL: Record<string, string> = {
  дивиденды: 'Дивиденды',
  проценты: 'Проценты',
  доля_прибыли: 'Доля прибыли',
  тело_инвестиций: 'Тело инвестиций',
}

const RECIPIENT_LABEL: Record<string, string> = {
  инвестор: 'Инвестор',
  партнер: 'Партнер',
}

function accrualMonthShort(iso: string | undefined): string {
  if (!iso || iso.length < 7) return '—'
  const [y, m] = iso.slice(0, 10).split('-')
  return m && y ? `${m}.${y}` : '—'
}

export function TgInvestmentsReturnsPage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [rows, setRows] = useState<InvestReturnRow[]>([])
  const [companies, setCompanies] = useState<InvestCompanyRow[]>([])
  const [search, setSearch] = useState('')
  const [usesCompanies, setUsesCompanies] = useState(true)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setError(null)
      setLoading(true)
      try {
        const cfgPromise = getInvestmentFormConfig().catch(() => DEFAULT_INVESTMENT_FORM_CONFIG)
        const [items, companyRows, cfg] = await Promise.all([
          getInvestReturns(),
          getInvestCompanies(),
          cfgPromise,
        ])
        if (cancelled) return
        setRows(items)
        setCompanies(companyRows)
        setUsesCompanies(cfg.uses_companies)
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Ошибка загрузки')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const companyMap = useMemo(() => new Map(companies.map((c) => [c.id, c.name])), [companies])
  const companyLabel = (id: number | null): string => {
    if (id == null) return 'Без компании'
    return companyMap.get(id) || `Компания #${id}`
  }

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    const sorted = [...rows].sort((a, b) =>
      String(b.date || '').localeCompare(String(a.date || '')),
    )
    if (!q) return sorted
    return sorted.filter((row) =>
      JSON.stringify({ ...row, _company: companyLabel(row.company) }).toLowerCase().includes(q),
    )
  }, [rows, search, companyMap])

  return (
    <div className="tg-investments-page">
      <Button
        icon={<ArrowLeftOutlined />}
        size="large"
        onClick={() => { tgHaptic.tap(); navigate('/tg/investments') }}
        style={{ marginBottom: 12, borderRadius: 12 }}
      >
        Назад
      </Button>

      <Typography.Title level={4} style={{ margin: '0 0 16px', fontWeight: 700 }}>
        Выплаты
      </Typography.Title>

      <Button
        type="primary"
        icon={<PlusOutlined />}
        size="large"
        onClick={() => { tgHaptic.tap(); navigate('/tg/investments/returns/new') }}
        style={{ marginBottom: 12, borderRadius: 12, width: '100%' }}
      >
        Создать выплату
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
          {rows.length === 0 ? 'Выплат пока нет.' : 'Ничего не найдено.'}
        </Typography.Paragraph>
      ) : null}

      {!loading && !error
        ? filtered.map((row) => (
            <div key={row.id} className="tg-request-row" style={{ cursor: 'default' }}>
              {usesCompanies ? (
                <div className="tg-request-row-title">{companyLabel(row.company)}</div>
              ) : null}
              <div className="tg-request-row-meta">
                <span className="tg-request-row-amount">{formatAmount(row.sum, row.currency)}</span>
                <Tag color={row.confirmed ? 'green' : 'default'}>
                  {row.confirmed ? 'Подтверждено' : 'Не подтверждено'}
                </Tag>
                <span>{TYPE_LABEL[row.type] || row.type || '—'}</span>
                <span>{RECIPIENT_LABEL[row.recipient] || row.recipient || '—'}</span>
                <span>Нач.: {accrualMonthShort(row.billing_date)}</span>
                <span>{formatDate(row.date)}</span>
                {row.comment ? <span>{row.comment}</span> : null}
              </div>
            </div>
          ))
        : null}
    </div>
  )
}
