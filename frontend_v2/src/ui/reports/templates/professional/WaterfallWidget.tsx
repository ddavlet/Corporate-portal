import type { StatementColumn, StatementResponse } from '../../../../lib/reportsApi'
import { formatAmount, UNITS_LABEL, type Units } from '../../../../lib/reportsFormat'
import { buildWaterfall, wrapLabel, type WaterfallStep } from './waterfall'

type Props = { statement: StatementResponse; column: StatementColumn; units: Units; onDrill: (rowId: string) => void }

const TITLES = { pnl: 'От выручки к прибыли', cashflow: 'От остатка к остатку' } as const

/** Axis labels are 11px: about 6.6px a letter. */
const LETTER_WIDTH = 6.6
const LINE_HEIGHT = 13

export function WaterfallWidget({ statement, column, units, onDrill }: Props) {
  const steps = buildWaterfall(statement, column.key)
  const hasMoney = steps.some((step) => step.value !== 0)
  const W = Math.max(480, steps.length * 76)
  const band = W / Math.max(1, steps.length)
  // Names wrap between words instead of being cut; the axis grows by the lines the longest name needs.
  const labels = steps.map((step) => wrapLabel(step.label, Math.max(8, Math.floor((band - 8) / LETTER_WIDTH))))
  const labelLines = Math.max(1, ...labels.map((lines) => lines.length))
  const top = 26
  const bottom = 18 + labelLines * LINE_HEIGHT
  const H = 226 + labelLines * LINE_HEIGHT
  const values = steps.flatMap((step) => [step.from, step.to])
  const high = Math.max(0, ...values)
  const low = Math.min(0, ...values)
  const y = (value: number) => top + ((high - value) / (high - low || 1)) * (H - top - bottom)
  const barW = Math.min(36, band * 0.6)
  const tone = (step: WaterfallStep) =>
    step.kind === 'up' ? 'rp-wf-up' : step.kind === 'down' ? 'rp-wf-down' : step.to < 0 ? 'rp-wf-loss' : 'rp-wf-total'
  const text = (step: WaterfallStep) => {
    const amount = formatAmount(String(Math.abs(step.value)), units)
    return step.kind === 'down' || (step.kind !== 'up' && step.value < 0) ? `−${amount}` : amount
  }
  return (
    <section className="rp-card rp-reveal rp-no-print" style={{ ['--rp-delay' as string]: '240ms' }}>
      <header className="rp-card-head">
        <div>
          <h3>{TITLES[statement.report]}</h3>
          <small>{`${statement.meta.period_label} · ${UNITS_LABEL[units]}`}</small>
        </div>
      </header>
      {!hasMoney ? (
        <p className="rp-empty-note">Нет данных за период.</p>
      ) : (
        <div className="rp-wf-scroll">
          <svg className="rp-wf" viewBox={`0 0 ${W} ${H}`} role="group" aria-label={TITLES[statement.report]}>
            <line className="rp-grid" x1={0} x2={W} y1={y(0)} y2={y(0)} />
            {steps.map((step, index) => {
              const x = band * index + (band - barW) / 2
              const yTop = y(Math.max(step.from, step.to))
              const height = Math.max(1, Math.abs(y(step.from) - y(step.to)))
              const rowId = step.rowId
              const next = steps[index + 1]
              const open = () => {
                if (rowId) onDrill(rowId)
              }
              return (
                <g key={step.key}>
                  <rect
                    className={`${tone(step)} rp-grow${step.to < step.from ? ' rp-grow--down' : ''}${rowId ? ' rp-wf-bar' : ''}`}
                    style={{ ['--rp-delay' as string]: `${index * 70}ms` }}
                    x={x}
                    y={yTop}
                    width={barW}
                    height={height}
                    rx={4}
                    role={rowId ? 'button' : undefined}
                    tabIndex={rowId ? 0 : undefined}
                    aria-label={rowId ? `${step.label}: ${text(step)} ${UNITS_LABEL[units]}` : undefined}
                    onClick={rowId ? open : undefined}
                    onKeyDown={
                      rowId
                        ? (event) => {
                            if (event.key === 'Enter' || event.key === ' ') {
                              event.preventDefault()
                              open()
                            }
                          }
                        : undefined
                    }
                  >
                    <title>{`${step.label}: ${text(step)} ${UNITS_LABEL[units]}`}</title>
                  </rect>
                  <text className="rp-wf-value rp-num" x={x + barW / 2} y={yTop - 6} textAnchor="middle">
                    {text(step)}
                  </text>
                  <text className="rp-axis rp-wf-label" x={x + barW / 2} y={H - bottom + 18} textAnchor="middle">
                    {labels[index].map((line, lineIndex) => (
                      <tspan key={lineIndex} x={x + barW / 2} dy={lineIndex === 0 ? 0 : LINE_HEIGHT}>
                        {line}
                      </tspan>
                    ))}
                  </text>
                  {next ? <line className="rp-wf-link" x1={x + barW} x2={x + band} y1={y(step.to)} y2={y(step.to)} /> : null}
                </g>
              )
            })}
          </svg>
        </div>
      )}
    </section>
  )
}
