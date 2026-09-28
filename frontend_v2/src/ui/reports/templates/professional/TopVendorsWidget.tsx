import { Button, Skeleton } from 'antd'
import { useEffect, useState } from 'react'
import { getStatementVendors, type ReportKind, type StatementVendorsResponse } from '../../../../lib/reportsApi'
import { describeReportError } from '../../../../lib/reportErrors'
import { formatAmount, formatRange, UNITS_SHORT, type Units } from '../../../../lib/reportsFormat'
import { initialsOf, PALETTE, pluralRu } from './reportVisuals'

type Props = {
  template: string
  report: ReportKind
  from: string
  to: string
  units: Units
  onOpenVendor: (vendor: string) => void
}

const LIMIT = 6

/** The vendors the period's requests paid most; a click opens their requests. Loads on its own, fails on its own. */
export function TopVendorsWidget({ template, report, from, to, units, onOpenVendor }: Props) {
  const [data, setData] = useState<StatementVendorsResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    getStatementVendors({ template, report, from, to, limit: LIMIT }, controller.signal)
      .then((res) => setData(res))
      .catch((e: unknown) => {
        if ((e as { name?: string } | null)?.name === 'AbortError') return
        setError(describeReportError(e, 'Не удалось загрузить поставщиков'))
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [template, report, from, to, attempt])

  const items = data?.items ?? []
  const top = Math.max(1, ...items.map((item) => Number(item.amount)))
  let body
  if (error) {
    body = (
      <div className="rp-widget-error">
        <span>{error}</span>
        <Button size="small" onClick={() => setAttempt((value) => value + 1)}>
          Повторить
        </Button>
      </div>
    )
  } else if (loading && !data) {
    body = <Skeleton active title={false} paragraph={{ rows: 4 }} style={{ padding: '0 16px 16px' }} />
  } else if (items.length === 0) {
    body = <p className="rp-empty-note">За период нет заявок с поставщиком.</p>
  } else {
    body = (
      <div className="rp-vendors">
        {items.map((item, index) => {
          const color = PALETTE[index % (PALETTE.length - 1)]
          return (
            <button
              key={item.vendor}
              type="button"
              className="rp-vendor"
              aria-label={`${item.vendor}: ${formatAmount(item.amount, units)} ${UNITS_SHORT[units]}, показать заявки`}
              onClick={() => onOpenVendor(item.vendor)}
            >
              <span className="rp-avatar" style={{ background: color }}>
                {initialsOf(item.vendor)}
              </span>
              <span className="rp-vendor-main">
                <span className="rp-vendor-name">{item.vendor}</span>
                <span className="rp-vendor-meta">{`${item.requests} ${pluralRu(item.requests, 'заявка', 'заявки', 'заявок')} · ${item.line_label}`}</span>
                <span className="rp-vendor-bar">
                  <i
                    className="rp-widen"
                    style={{ width: `${(Number(item.amount) / top) * 100}%`, background: color, ['--rp-delay' as string]: `${index * 70}ms` }}
                  />
                </span>
              </span>
              <span className="rp-vendor-sum rp-num">
                {formatAmount(item.amount, units)}
                <small>{UNITS_SHORT[units]}</small>
              </span>
            </button>
          )
        })}
      </div>
    )
  }
  return (
    <section
      className={`rp-card rp-reveal rp-no-print${loading && data ? ' is-refreshing' : ''}`}
      style={{ ['--rp-delay' as string]: '300ms' }}
    >
      <header className="rp-card-head">
        <div>
          <h3>Крупные поставщики</h3>
          <small>{`${formatRange(from, to)} · по заявкам`}</small>
        </div>
      </header>
      {body}
    </section>
  )
}
