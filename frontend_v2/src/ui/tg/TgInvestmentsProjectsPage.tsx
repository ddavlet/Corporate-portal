import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Input, Skeleton, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import { ArrowLeftOutlined, SearchOutlined } from '@ant-design/icons'
import {
  getInvestCompanies,
  getProjectInvestments,
  type InvestCompanyRow,
  type ProjectInvestmentRow,
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

export function TgInvestmentsProjectsPage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [rows, setRows] = useState<ProjectInvestmentRow[]>([])
  const [companies, setCompanies] = useState<InvestCompanyRow[]>([])
  const [search, setSearch] = useState('')

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setError(null)
      setLoading(true)
      try {
        const [items, companyRows] = await Promise.all([
          getProjectInvestments(),
          getInvestCompanies(),
        ])
        if (cancelled) return
        setRows(items)
        setCompanies(companyRows)
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
        onClick={() => navigate('/tg/investments')}
        style={{ marginBottom: 12, borderRadius: 12 }}
      >
        Назад
      </Button>

      <Typography.Title level={4} style={{ margin: '0 0 16px', fontWeight: 700 }}>
        Вложения
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

      {!loading && !error && filtered.length === 0 ? (
        <Typography.Paragraph type="secondary" style={{ textAlign: 'center', padding: '24px 8px' }}>
          {rows.length === 0 ? 'Вложений пока нет.' : 'Ничего не найдено.'}
        </Typography.Paragraph>
      ) : null}

      {!loading && !error
        ? filtered.map((row) => (
            <div key={row.id} className="tg-request-row" style={{ cursor: 'default' }}>
              <div className="tg-request-row-title">{companyLabel(row.company)}</div>
              <div className="tg-request-row-meta">
                <span className="tg-request-row-amount">{formatAmount(row.amount, row.currency)}</span>
                <span>{formatDate(row.date)}</span>
                {row.comment ? <span>{row.comment}</span> : null}
              </div>
            </div>
          ))
        : null}
    </div>
  )
}
