import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Select, Skeleton, Tag, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import { ArrowLeftOutlined } from '@ant-design/icons'
import { getInvestPayoutSchedule, type InvestPayoutScheduleRow } from '../../lib/api'
import { AdminEditRecordButton } from '../admin/AdminEditRecordButton'
import { tgHaptic } from './tgHaptic'

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

export function TgInvestmentsSchedulePage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [paidFilter, setPaidFilter] = useState<PaidFilter>('all')
  const [rows, setRows] = useState<InvestPayoutScheduleRow[]>([])

  const loadRows = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setRows(await getInvestPayoutSchedule())
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
    const byPaid = paidFilter === 'all' ? rows : rows.filter((r) => (paidFilter === 'paid' ? r.is_paid : !r.is_paid))
    return [...byPaid].sort((a, b) => new Date(a.payout_date).getTime() - new Date(b.payout_date).getTime())
  }, [rows, paidFilter])

  return (
    <div className="tg-schedule-page">
      <Button
        icon={<ArrowLeftOutlined />}
        size="large"
        onClick={() => { tgHaptic.tap(); navigate('/tg/investments') }}
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
            <div key={r.id} style={{ marginBottom: 10 }}>
              <div className="tg-request-row" style={{ marginBottom: 0 }}>
                <div className="tg-request-row-title">
                  #{r.id} · {dateText(r.payout_date)}
                </div>
                <div className="tg-request-row-meta">
                  <span className="tg-request-row-amount">{asMoney(r.amount, r.currency)}</span>
                  <Tag color={r.is_paid ? 'green' : 'orange'}>{r.is_paid ? 'Оплачено' : 'Не оплачено'}</Tag>
                  <span>Оплаченная сумма: {asMoney(r.payment_amount, r.currency)}</span>
                  <span>{r.comment || '-'}</span>
                </div>
              </div>
              <AdminEditRecordButton
                endpoint="/api/investments/payout-schedule/"
                record={r}
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
