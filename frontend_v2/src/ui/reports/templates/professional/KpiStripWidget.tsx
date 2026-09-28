import type { StatementKpi } from '../../../../lib/reportsApi'
import { formatAmount, formatDelta, formatRatio, isFavorable, UNITS_SHORT, type Units } from '../../../../lib/reportsFormat'
import { CountUpAmount } from './CountUpAmount'
import { Sparkline } from './Sparkline'

type Props = {
  kpis: StatementKpi[]
  units: Units
  /** The KPI already shown in the summary card. */
  exclude?: string
  /** KPIs a click can open (a statement row stands behind them). */
  openable?: ReadonlySet<string>
  onOpen?: (kpiId: string) => void
}

const POLARITY_DOT = { income: '#1f6feb', expense: '#e8664f', result: '#8b5cf6', neutral: '#64748b' } as const

export function KpiStripWidget({ kpis, units, exclude, openable, onOpen }: Props) {
  return (
    <div className="rp-kpis">
      {kpis
        .filter((kpi) => kpi.id !== exclude)
        .map((kpi, index) => {
          const clickable = Boolean(onOpen && openable?.has(kpi.id))
          const body = (
            <>
              <div className="rp-kpi-label">
                <i className="rp-kpi-dot" style={{ background: POLARITY_DOT[kpi.polarity] }} />
                {kpi.label}
              </div>
              <div className="rp-kpi-value rp-num">
                <CountUpAmount value={kpi.value} format={(value) => formatAmount(value, units)} />
                <small>{UNITS_SHORT[units]}</small>
                {kpi.ratio !== null ? <span className="rp-kpi-ratio">маржа {formatRatio(kpi.ratio)}</span> : null}
              </div>
              <div className="rp-kpi-deltas">
                {kpi.comparisons.map((comparison) => {
                  const view = formatDelta(comparison.delta_pct === null ? undefined : { pct: comparison.delta_pct })
                  const favorable = view ? isFavorable(kpi.polarity, view.direction) : null
                  const tone = favorable === null ? '' : favorable ? 'rp-good' : 'rp-bad'
                  return (
                    <span key={comparison.key}>
                      <span className={tone}>{view ? view.text : '—'}</span> <span className="rp-muted">{comparison.label}</span>
                    </span>
                  )
                })}
              </div>
              <Sparkline values={kpi.spark} />
            </>
          )
          const style = { ['--rp-delay' as string]: `${60 + index * 60}ms` }
          return clickable ? (
            <button
              key={kpi.id}
              type="button"
              className="rp-kpi rp-kpi--button rp-reveal"
              style={style}
              aria-label={`${kpi.label}: показать состав`}
              onClick={() => onOpen?.(kpi.id)}
            >
              {body}
            </button>
          ) : (
            <div key={kpi.id} className="rp-kpi rp-reveal" style={style}>
              {body}
            </div>
          )
        })}
    </div>
  )
}
