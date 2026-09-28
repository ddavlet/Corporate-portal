import type { StatementColumn, StatementResponse } from '../../../../lib/reportsApi'
import { formatAmount, formatDelta, formatRatio, isFavorable, UNITS_LABEL, type Units } from '../../../../lib/reportsFormat'
import { CountUpAmount } from './CountUpAmount'
import { REPORT_VISUALS, rowValue } from './reportVisuals'

type Props = { statement: StatementResponse; column: StatementColumn; units: Units }

const upperFirst = (text: string) => text.charAt(0).toUpperCase() + text.slice(1)

/** The period in one card: the headline number large, how it compares, and one sentence on what it is made of. */
export function SummaryHeroWidget({ statement, column, units }: Props) {
  const visuals = REPORT_VISUALS[statement.report]
  const kpi = statement.kpis.find((candidate) => candidate.id === visuals.heroKpi)
  if (!kpi) return null
  const marginRow = visuals.marginRow ? statement.rows.find((row) => row.id === visuals.marginRow) : undefined
  const margin = marginRow ? rowValue(statement, marginRow.id, column.key) : null
  const negative = Number(kpi.value) < 0
  return (
    <section className="rp-card rp-hero rp-reveal" aria-label={kpi.label}>
      <span className="rp-eyebrow">{`${kpi.label} · ${statement.meta.period_label}`}</span>
      <div className={`rp-hero-value rp-num${negative ? ' rp-neg' : ''}`}>
        <CountUpAmount value={kpi.value} format={(value) => formatAmount(value, units)} />
        <small>{UNITS_LABEL[units]}</small>
      </div>
      <div className="rp-chips">
        {kpi.ratio !== null ? <span className="rp-chip">{`маржа ${formatRatio(kpi.ratio)}`}</span> : null}
        {kpi.comparisons.map((comparison) => {
          const view = formatDelta(comparison.delta_pct === null ? undefined : { pct: comparison.delta_pct })
          if (!view) return null
          const favorable = isFavorable(kpi.polarity, view.direction)
          const tone = favorable === null ? '' : favorable ? ' rp-chip--good' : ' rp-chip--bad'
          return (
            <span key={comparison.key} className={`rp-chip${tone}`}>
              {`${view.text} ${comparison.label}`}
            </span>
          )
        })}
      </div>
      <p className="rp-story">
        {visuals.narrative(statement, column.key, units).map((part, index) =>
          part.strong ? (
            <b key={index} className="rp-num">
              {part.text}
            </b>
          ) : (
            <span key={index}>{part.text}</span>
          ),
        )}
      </p>
      {marginRow && margin !== null ? (
        <div className="rp-meter-wrap">
          <div className="rp-meter" aria-hidden="true">
            <i style={{ width: `${Math.max(0, Math.min(100, margin * 100))}%` }} />
          </div>
          <div className="rp-meter-legend">
            <span>{upperFirst(marginRow.label)}</span>
            <span className="rp-num">{formatRatio(String(margin))}</span>
          </div>
        </div>
      ) : null}
    </section>
  )
}
