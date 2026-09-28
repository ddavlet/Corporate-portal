import type { StatementColumn, StatementResponse } from '../../../../lib/reportsApi'
import { formatAmount, UNITS_LABEL, UNITS_SHORT, type Units } from '../../../../lib/reportsFormat'
import { expenseSlices } from './expenseStructure'
import { REPORT_VISUALS } from './reportVisuals'

type Props = { statement: StatementResponse; column: StatementColumn; units: Units; onDrill: (rowId: string) => void }

const RADIUS = 66
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

/** Where the money went: the report's expense group as a ring, with a legend that opens each line. */
export function ExpenseStructureWidget({ statement, column, units, onDrill }: Props) {
  const groupId = REPORT_VISUALS[statement.report].structureRow
  const group = statement.rows.find((row) => row.id === groupId)
  const slices = expenseSlices(statement, groupId, column.key)
  const total = slices.reduce((sum, slice) => sum + slice.value, 0)
  const starts = slices.map((_, index) => slices.slice(0, index).reduce((sum, slice) => sum + slice.share * CIRCUMFERENCE, 0))
  return (
    <section className="rp-card rp-reveal rp-no-print" style={{ ['--rp-delay' as string]: '180ms' }}>
      <header className="rp-card-head">
        <div>
          <h3>Куда уходят деньги</h3>
          <small>{`${group?.label ?? ''} · ${statement.meta.period_label}`}</small>
        </div>
      </header>
      {slices.length === 0 ? (
        <p className="rp-empty-note">Расходов за период нет.</p>
      ) : (
        <div className="rp-ring-wrap">
          <svg className="rp-ring" viewBox="0 0 170 170" aria-hidden="true">
            <g transform="rotate(-90 85 85)">
              {slices.map((slice, index) => (
                <circle
                  key={slice.key}
                  className="rp-ring-seg"
                  style={{ stroke: slice.color, ['--rp-delay' as string]: `${index * 80}ms` }}
                  cx={85}
                  cy={85}
                  r={RADIUS}
                  strokeDasharray={`${Math.max(0, slice.share * CIRCUMFERENCE - (slices.length > 1 ? 2 : 0))} ${CIRCUMFERENCE}`}
                  strokeDashoffset={-starts[index]}
                  onClick={() => onDrill(slice.rowId)}
                >
                  <title>{`${slice.label}: ${formatAmount(String(slice.value), units)} ${UNITS_SHORT[units]}`}</title>
                </circle>
              ))}
            </g>
            <text className="rp-ring-total rp-num" x={85} y={86} textAnchor="middle">
              {formatAmount(String(total), units)}
            </text>
            <text className="rp-ring-sub" x={85} y={104} textAnchor="middle">
              {UNITS_LABEL[units]}
            </text>
          </svg>
          <div className="rp-ring-legend">
            {slices.map((slice) => (
              <button
                key={slice.key}
                type="button"
                className="rp-ring-row"
                aria-label={`${slice.label}: ${formatAmount(String(slice.value), units)} ${UNITS_SHORT[units]}`}
                onClick={() => onDrill(slice.rowId)}
              >
                <i style={{ background: slice.color }} />
                <span className="rp-ring-label">{slice.label}</span>
                <span className="rp-num">{formatAmount(String(slice.value), units)}</span>
                <em>{`${Math.round(slice.share * 100)}%`}</em>
              </button>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}
