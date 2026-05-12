import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Select, Skeleton, Tag, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import { ArrowLeftOutlined } from '@ant-design/icons'
import { getInvestCompanies, getInvestPayoutSchedule, type InvestCompanyRow, type InvestPayoutScheduleRow } from '../../lib/api'

type CompanyFilter = 'all' | 'none' | number
type PaidFilter = 'all' | 'paid' | 'unpaid'

const moneyFmt = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 })

function asMoney(value: string | number, currency?: string): string {
  const n = typeof value === 'number' ? value : Number(String(value).replace(',', '.'))
  const amountText = Number.isFinite(n) ? moneyFmt.format(n) : '0'
  return currency ? `${amountText} ${currency}` : amountText
}

function dateText(value: string): string {
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value || '-'
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    timeZone: 'Asia/Tashkent',
  }).format(d)
}

function byCompany<T extends { company: number | null }>(rows: T[], filter: CompanyFilter): T[] {
  if (filter === 'all') return rows
  if (filter === 'none') return rows.filter((r) => r.company == null)
  return rows.filter((r) => r.company === filter)
}

export function TgInvestmentsSchedulePage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [companyFilter, setCompanyFilter] = useState<CompanyFilter>('all')
  const [paidFilter, setPaidFilter] = useState<PaidFilter>('all')
  const [companies, setCompanies] = useState<InvestCompanyRow[]>([])
  const [rows, setRows] = useState<InvestPayoutScheduleRow[]>([])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setError(null)
      try {
        const [c, s] = await Promise.all([getInvestCompanies(), getInvestPayoutSchedule()])
        if (cancelled) return
        setCompanies(c)
        setRows(s)
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
  const companyLabel = (id: number | null) => {
    if (id == null) return 'Без компании'
    return companyMap.get(id) || `#${id}`
  }

  const filtered = useMemo(() => {
    const filteredByCompany = byCompany(rows, companyFilter)
    const byPaid =
      paidFilter === 'all'
        ? filteredByCompany
        : filteredByCompany.filter((r) => (paidFilter === 'paid' ? r.is_paid : !r.is_paid))
    return [...byPaid].sort((a, b) => new Date(a.payout_date).getTime() - new Date(b.payout_date).getTime())
  }, [rows, companyFilter, paidFilter])

  const companyOptions = [
    { label: 'Все компании', value: 'all' },
    { label: 'Без компании', value: 'none' },
    ...companies.map((c) => ({ label: c.name, value: c.id })),
  ]

  return (
    <div className="tg-schedule-page">
      <Button
        icon={<ArrowLeftOutlined />}
        size="large"
        onClick={() => navigate('/tg/investments')}
        style={{ marginBottom: 12, borderRadius: 12 }}
      >
        Назад
      </Button>

      <Typography.Title level={4} style={{ margin: '0 0 16px', fontWeight: 700 }}>
        Расписание выплат
      </Typography.Title>

      <div className="tg-filters-grid">
        <Select
          size="large"
          options={companyOptions}
          value={companyFilter}
          onChange={(v) => setCompanyFilter(v as CompanyFilter)}
        />
        <Select
          size="large"
          options={[
            { label: 'Все статусы', value: 'all' },
            { label: 'Оплачено', value: 'paid' },
            { label: 'Не оплачено', value: 'unpaid' },
          ]}
          value={paidFilter}
          onChange={(v) => setPaidFilter(v as PaidFilter)}
        />
      </div>

      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 12, borderRadius: 12 }} /> : null}
      {loading ? <Skeleton active paragraph={{ rows: 6 }} /> : null}

      {!loading && !error && filtered.length === 0 ? (
        <Typography.Paragraph type="secondary" style={{ textAlign: 'center', padding: '24px 8px' }}>
          Записей не найдено.
        </Typography.Paragraph>
      ) : null}

      {!loading && !error
        ? filtered.map((r) => (
            <div key={r.id} className="tg-request-row">
              <div className="tg-request-row-title">
                #{r.id} · {dateText(r.payout_date)}
              </div>
              <div className="tg-request-row-meta">
                <span className="tg-request-row-amount">{asMoney(r.amount, r.currency)}</span>
                <Tag color={r.is_paid ? 'green' : 'orange'}>{r.is_paid ? 'Оплачено' : 'Не оплачено'}</Tag>
                <span>Оплаченная сумма: {asMoney(r.payment_amount, r.currency)}</span>
                <span>{companyLabel(r.company)}</span>
                <span>{r.comment || '-'}</span>
              </div>
            </div>
          ))
        : null}
    </div>
  )
}
