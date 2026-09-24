import { Button, Empty } from 'antd'
import type { ReportKind, StatementChart } from '../../../../lib/reportsApi'
import { formatAmount, UNITS_LABEL, type Units } from '../../../../lib/reportsFormat'

type Props = { chart: StatementChart; units: Units; report: ReportKind; collapsed: boolean; onToggle: () => void }

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

function ChartSvg({ chart, units, labels }: { chart: StatementChart; units: Units; labels: [string, string, string] }) {
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
  const bar = (index: number, value: number | null, offset: number, className: string) => {
    if (value === null || value === 0) return null
    const y0 = y(0)
    const yv = y(value)
    return <rect className={className} x={cx(index) + offset} y={Math.min(y0, yv)} width={barW} height={Math.abs(y0 - yv)} rx={2} />
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
      />
    )
  })
  return (
    <svg className="rp-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${labels[0]} и ${labels[1].toLowerCase()} столбцами, ${labels[2].toLowerCase()} линией`}>
      {ticks.map((tick) => (
        <g key={tick}>
          <line className="rp-grid" x1={left} x2={W - right} y1={y(tick)} y2={y(tick)} />
          <text className="rp-axis" x={left - 8} y={y(tick) + 4} textAnchor="end">{tickLabel(tick)}</text>
        </g>
      ))}
      {chart.labels.map((label, index) => (
        <g key={`${label}-${index}`} className={chart.partial[index] ? 'rp-bar-partial' : undefined}>
          <title>
            {`${label}: ${labels[0]} ${formatAmount(chart.inflow[index], units)} · ${labels[1]} ${formatAmount(chart.outflow[index], units)} · ${labels[2]} ${formatAmount(chart.net[index], units)} (${UNITS_LABEL[units]})`}
          </title>
          {bar(index, inflow[index], -barW - 1, 'rp-bar-in')}
          {bar(index, outflow[index], 1, 'rp-bar-out')}
          <text className="rp-axis" x={cx(index)} y={H - 8} textAnchor="middle">{label}</text>
        </g>
      ))}
      {netSegments}
      {net.map((value, index) =>
        value === null ? null : (
          <circle key={index} className="rp-net-dot" cx={cx(index)} cy={y(value)} r={4} fillOpacity={chart.partial[index] ? 0.45 : 1} />
        ),
      )}
    </svg>
  )
}

export function TrendChartWidget({ chart, units, report, collapsed, onToggle }: Props) {
  const labels = SERIES[report]
  return (
    <section className="rp-card">
      <header className="rp-card-head">
        <div>
          <h3>Динамика</h3>
          <small>{UNITS_LABEL[units]}</small>
        </div>
        <div className="rp-legend">
          <span><i style={{ background: '#1677ff' }} />{labels[0]}</span>
          <span><i style={{ background: '#b3bdcb' }} />{labels[1]}</span>
          <span><i className="rp-legend-line" style={{ background: '#0c9a6f' }} />{labels[2]}</span>
          <Button type="link" size="small" onClick={onToggle} aria-expanded={!collapsed}>
            {collapsed ? 'Показать' : 'Свернуть'}
          </Button>
        </div>
      </header>
      {collapsed ? null : <ChartSvg chart={chart} units={units} labels={labels} />}
    </section>
  )
}
