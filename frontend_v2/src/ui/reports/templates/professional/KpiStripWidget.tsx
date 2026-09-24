import type { StatementKpi } from '../../../../lib/reportsApi'
import { formatAmount, formatDelta, formatRatio, isFavorable, UNITS_SHORT, type Units } from '../../../../lib/reportsFormat'
import { Sparkline } from './Sparkline'

export function KpiStripWidget({ kpis, units }: { kpis: StatementKpi[]; units: Units }) {
  return (
    <div className="rp-kpis">
      {kpis.map((kpi) => (
        <div key={kpi.id} className="rp-kpi">
          <div className="rp-kpi-label">{kpi.label}</div>
          <div className="rp-kpi-value">
            {formatAmount(kpi.value, units)}
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
        </div>
      ))}
    </div>
  )
}
