import { Button, Empty } from 'antd'
import { useState } from 'react'
import type { ReportKind, StatementChart } from '../../../../lib/reportsApi'
import { formatAmount, formatRatio, UNITS_LABEL, UNITS_SHORT, type Units } from '../../../../lib/reportsFormat'

type Props = {
  chart: StatementChart
  units: Units
  report: ReportKind
  collapsed: boolean
  onToggle: () => void
  /** Switch the report to one month (only for a bar that stands for exactly one month). */
  onFocusMonth?: (month: string) => void
}

const SERIES: Record<ReportKind, [string, string, string]> = {
  pnl: ['Выручка', 'Расходы', 'Чистая прибыль'],
  cashflow: ['Поступления', 'Выплаты', 'Чистый денежный поток'],
}

function niceTicks(min: number, max: number, count: number): number[] {
  const span = max - min || 1
  const raw = span / count
  const magnitude = 10 ** Math.floor(Math.log10(raw))
  const normalized = raw / magnitude
  const step = (normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 2.5 ? 2.5 : normalized <= 5 ? 5 : 10) * magnitude
  const ticks: number[] = []
  for (let value = Math.floor(min / step) * step; value <= Math.ceil(max / step) * step + step / 2; value += step) ticks.push(value)
  return ticks
}

type ChartProps = {
  chart: StatementChart
  units: Units
  labels: [string, string, string]
  report: ReportKind
  onFocusMonth?: (month: string) => void
}

function ChartSvg({ chart, units, labels, report, onFocusMonth }: ChartProps) {
  const [hovered, setHovered] = useState<number | null>(null)
  const toNumbers = (series: (string | null)[]) => series.map((value) => (value === null ? null : Number(value)))
  const inflow = toNumbers(chart.inflow)
  const outflow = toNumbers(chart.outflow)
  const net = toNumbers(chart.net)
  const count = chart.labels.length
  if (count === 0) return <Empty description="Нет данных за период" image={Empty.PRESENTED_IMAGE_SIMPLE} />
  const known = [...inflow, ...outflow, ...net].filter((value): value is number => value !== null)
  const ticks = niceTicks(Math.min(0, ...known), Math.max(0, ...known), 4)
  const [low, high] = [ticks[0], ticks[ticks.length - 1]]
  const W = 960
  const H = 240
  const left = 60
  const right = 12
  const top = 16
  const bottom = 28
  const plotW = W - left - right
  const plotH = H - top - bottom
  const y = (value: number) => top + plotH - ((value - low) / (high - low || 1)) * plotH
  const band = plotW / count
  const barW = Math.max(3, Math.min(22, (band - 10) / 2))
  const cx = (index: number) => left + band * (index + 0.5)
  const tickLabel = (value: number) => (value === 0 ? '0' : formatAmount(String(value), units))
  // A bar opens its month only when it stands for exactly one month that has data.
  const monthOf = (index: number): string | null => {
    const months = chart.months?.[index]
    return onFocusMonth && months?.length === 1 && chart.inflow[index] !== null ? months[0] : null
  }
  const bar = (index: number, value: number | null, offset: number, className: string, delay: number) => {
    if (value === null || value === 0) return null
    const y0 = y(0)
    const yv = y(value)
    return (
      <rect
        className={`${className} rp-grow${value < 0 ? ' rp-grow--down' : ''}`}
        style={{ ['--rp-delay' as string]: `${delay}ms` }}
        x={cx(index) + offset}
        y={Math.min(y0, yv)}
        width={barW}
        height={Math.abs(y0 - yv)}
        rx={3}
        pointerEvents="none"
      />
    )
  }
  // A segment that reaches an unfinished month is dashed, like its paler bars.
  const netPoints = net.map((value, index) => (value === null ? null : { x: cx(index), y: y(value), partial: chart.partial[index] }))
  const netSegments = netPoints.slice(1).map((point, index) => {
    const previous = netPoints[index]
    if (!point || !previous) return null
    return (
      <line
        key={index}
        className={point.partial || previous.partial ? 'rp-net rp-net--partial' : 'rp-net'}
        x1={previous.x}
        y1={previous.y}
        x2={point.x}
        y2={point.y}
        pointerEvents="none"
      />
    )
  })
  const money = (value: string | null) => `${formatAmount(value, units)} ${UNITS_SHORT[units]}`
  const tip =
    hovered === null ? null : (
      // Centred over the month, but kept inside the card at the first and last months.
      <div className="rp-chart-tip" style={{ left: `${Math.min(88, Math.max(12, (cx(hovered) / W) * 100))}%` }} role="status">
        <b>{chart.labels[hovered]}</b>
        <div>
          <span>{labels[0]}</span>
          {money(chart.inflow[hovered])}
        </div>
        <div>
          <span>{labels[1]}</span>
          {money(chart.outflow[hovered])}
        </div>
        <div>
          <span>{labels[2]}</span>
          {money(chart.net[hovered])}
        </div>
        {report === 'pnl' && Number(chart.inflow[hovered]) > 0 ? (
          <div>
            <span>Маржа</span>
            {formatRatio(String(Number(chart.net[hovered]) / Number(chart.inflow[hovered])))}
          </div>
        ) : null}
        {monthOf(hovered) ? <em>Нажмите, чтобы открыть месяц</em> : null}
      </div>
    )
  return (
    <div className="rp-chart-box">
      <svg
        className="rp-chart"
        viewBox={`0 0 ${W} ${H}`}
        role="group"
        aria-label={`${labels[0]} и ${labels[1].toLowerCase()} столбцами, ${labels[2].toLowerCase()} линией`}
      >
        {ticks.map((tick) => (
          <g key={tick}>
            <line className="rp-grid" x1={left} x2={W - right} y1={y(tick)} y2={y(tick)} />
            <text className="rp-axis" x={left - 8} y={y(tick) + 4} textAnchor="end">
              {tickLabel(tick)}
            </text>
          </g>
        ))}
        {chart.labels.map((label, index) => {
          const month = monthOf(index)
          const pick = () => {
            if (month) onFocusMonth?.(month)
          }
          return (
            <g key={`${label}-${index}`} className={chart.partial[index] ? 'rp-bar-partial' : undefined}>
              <rect
                className={`rp-col-hit${hovered === index ? ' is-hover' : ''}${month ? ' is-clickable' : ''}`}
                x={left + band * index + 2}
                y={top}
                width={Math.max(1, band - 4)}
                height={plotH}
                rx={8}
                role={month ? 'button' : undefined}
                tabIndex={month ? 0 : undefined}
                aria-label={month ? `${label}: показать месяц` : undefined}
                onMouseEnter={() => setHovered(index)}
                onMouseLeave={() => setHovered(null)}
                onFocus={() => setHovered(index)}
                onBlur={() => setHovered(null)}
                onClick={pick}
                onKeyDown={(event) => {
                  if (month && (event.key === 'Enter' || event.key === ' ')) {
                    event.preventDefault()
                    pick()
                  }
                }}
              />
              {bar(index, inflow[index], -barW - 1, 'rp-bar-in', index * 40)}
              {bar(index, outflow[index], 1, 'rp-bar-out', index * 40 + 20)}
              <text className="rp-axis" x={cx(index)} y={H - 8} textAnchor="middle">
                {label}
              </text>
            </g>
          )
        })}
        {netSegments}
        {net.map((value, index) =>
          value === null ? null : (
            <circle
              key={index}
              className="rp-net-dot"
              cx={cx(index)}
              cy={y(value)}
              r={hovered === index ? 6 : 4}
              fillOpacity={chart.partial[index] ? 0.45 : 1}
              pointerEvents="none"
            />
          ),
        )}
      </svg>
      {tip}
    </div>
  )
}

export function TrendChartWidget({ chart, units, report, collapsed, onToggle, onFocusMonth }: Props) {
  const labels = SERIES[report]
  const clickable = Boolean(onFocusMonth && chart.months?.some((months) => months.length === 1))
  return (
    <section className="rp-card rp-reveal" style={{ ['--rp-delay' as string]: '120ms' }}>
      <header className="rp-card-head">
        <div>
          <h3>Динамика</h3>
          <small>{clickable ? `${UNITS_LABEL[units]} · нажмите на месяц, чтобы открыть его` : UNITS_LABEL[units]}</small>
        </div>
        <div className="rp-legend">
          <span>
            <i style={{ background: '#1677ff' }} />
            {labels[0]}
          </span>
          <span>
            <i style={{ background: '#b3bdcb' }} />
            {labels[1]}
          </span>
          <span>
            <i className="rp-legend-line" style={{ background: '#0c9a6f' }} />
            {labels[2]}
          </span>
          <Button type="link" size="small" onClick={onToggle} aria-expanded={!collapsed}>
            {collapsed ? 'Показать' : 'Свернуть'}
          </Button>
        </div>
      </header>
      {collapsed ? null : <ChartSvg chart={chart} units={units} labels={labels} report={report} onFocusMonth={onFocusMonth} />}
    </section>
  )
}
