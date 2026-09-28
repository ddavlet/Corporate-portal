import { ArrowDownOutlined, ArrowUpOutlined, DownOutlined, RightOutlined } from '@ant-design/icons'
import { Button, Table, Tooltip } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useMemo, type ReactNode } from 'react'
import type { StatementColumn, StatementResponse, StatementRow } from '../../../../lib/reportsApi'
import { formatAmount, formatDelta, formatRatio, isFavorable, UNITS_LABEL, type Units } from '../../../../lib/reportsFormat'
import { cellInsight } from './cellInsight'
import { flattenStatementRows, type DisplayRow } from './flattenStatementRows'

type Props = {
  statement: StatementResponse
  units: Units
  open: ReadonlySet<string>
  selected: { rowId: string; columnKey: string } | null
  onToggle: (rowId: string) => void
  onDrill: (rowId: string, column: StatementColumn) => void
  /** Only these columns are shown (phone layout); every column when omitted. */
  columnKeys?: ReadonlySet<string>
  /** Narrow label column with wrapping labels (phone layout). */
  compact?: boolean
  /** The row a KPI tile points to; highlighted for a moment. */
  flashRowId?: string | null
}

const lowerFirst = (text: string) => text.charAt(0).toLowerCase() + text.slice(1)

function withInsight(statement: StatementResponse, row: StatementRow, column: StatementColumn, content: ReactNode) {
  const render = () => {
    const lines = cellInsight(statement, row, column)
    if (lines.length === 0) return null
    return (
      <div className="rp-insight">
        {lines.map((line) => (
          <div key={line.label}>
            <span>{line.label}</span>
            <b className={line.tone === 'good' ? 'rp-insight-good' : line.tone === 'bad' ? 'rp-insight-bad' : undefined}>{line.text}</b>
          </div>
        ))}
      </div>
    )
  }
  return (
    <Tooltip title={render} mouseEnterDelay={0.3} placement="top">
      {content}
    </Tooltip>
  )
}

const TREND_COLORS: Record<StatementRow['polarity'], string> = {
  income: '#1f6feb',
  expense: '#e8664f',
  result: '#8b5cf6',
  neutral: '#64748b',
}

function MiniTrend({ values, polarity }: { values: (string | null)[]; polarity: StatementRow['polarity'] }) {
  const points = values.map((value) => Number(value ?? 0) || 0)
  if (points.length < 2 || points.every((value) => value === 0)) return null
  const min = Math.min(...points)
  const range = Math.max(...points) - min || 1
  const path = points
    .map((value, index) => `${index ? 'L' : 'M'}${((index / (points.length - 1)) * 88 + 1).toFixed(1)},${(22 - ((value - min) / range) * 20).toFixed(1)}`)
    .join('')
  return (
    <svg className="rp-trend" viewBox="0 0 90 24" aria-hidden="true">
      <path d={path} style={{ stroke: TREND_COLORS[polarity] }} />
    </svg>
  )
}

function LabelCell({ display, compact, onToggle }: { display: DisplayRow; compact: boolean; onToggle: (rowId: string) => void }) {
  const row = display.row
  if (!row) return null
  const toggles = display.variant === 'header' || display.variant === 'collapsed' || display.variant === 'nested'
  const label = display.variant === 'total' ? `Итого ${lowerFirst(row.label)}` : row.label
  const indent = (display.variant === 'ratio' ? 1 : display.depth) * (compact ? 12 : 20)
  return (
    <div className="rp-label" style={{ paddingLeft: indent }}>
      {toggles ? (
        <Button
          type="text"
          size="small"
          aria-expanded={display.expanded}
          aria-label={`${display.expanded ? 'Свернуть' : 'Развернуть'}: ${row.label}`}
          icon={display.expanded ? <DownOutlined /> : <RightOutlined />}
          onClick={() => onToggle(row.id)}
        />
      ) : (
        <span className="rp-toggle-space" />
      )}
      <span className="rp-label-text">{label}</span>
      {row.hint ? <span className="rp-hint">{row.hint}</span> : null}
    </div>
  )
}

export function StatementTableWidget({
  statement,
  units,
  open,
  selected,
  onToggle,
  onDrill,
  columnKeys,
  compact = false,
  flashRowId = null,
}: Props) {
  const rows = useMemo(() => flattenStatementRows(statement.rows, open), [statement.rows, open])

  const columns = useMemo<ColumnsType<DisplayRow>>(() => {
    const visible = columnKeys ? statement.columns.filter((column) => columnKeys.has(column.key)) : statement.columns
    const lastPeriod = visible.reduce((last, column, index) => (column.kind === 'period' ? index : last), -1)
    // A narrow phone table scrolls as a whole; pinned totals would leave no room for the period.
    const pinRight = !compact && visible.some((column) => column.key === 'total')
    const periodColumns = visible.filter((column) => column.kind === 'period')
    // Size bars and trends compare periods; with fewer than three there is nothing to compare.
    const rich = !compact && periodColumns.length >= 3
    const rowMax = (row: StatementRow) =>
      Math.max(0, ...periodColumns.map((column) => Math.abs(Number(row.values[column.key] ?? 0)) || 0))

    const renderValue = (display: DisplayRow, column: StatementColumn) => {
      const row = display.row
      if (!row || display.variant === 'header') return null
      if (column.kind === 'delta') {
        const view = formatDelta(row.deltas[column.key] ?? undefined)
        if (!view) return <span className="rp-muted">—</span>
        const favorable = isFavorable(row.polarity, view.direction)
        const tone = favorable === null ? '' : favorable ? ' rp-good' : ' rp-bad'
        return (
          <span className={`rp-delta${tone}`}>
            {view.direction === 'up' ? <ArrowUpOutlined /> : view.direction === 'down' ? <ArrowDownOutlined /> : null}
            {view.text}
          </span>
        )
      }
      const value = row.values[column.key] ?? null
      if (row.kind === 'ratio') return <span className="rp-muted">{formatRatio(value)}</span>
      const text = formatAmount(value, units)
      if (text === '—') return <span className="rp-muted">—</span>
      const negative = Number(value) < 0 && (row.kind === 'result' || row.kind === 'balance')
      if (!row.drillable) return withInsight(statement, row, column, <span className={negative ? 'rp-neg' : undefined}>{text}</span>)
      const isSelected = selected?.rowId === row.id && selected.columnKey === column.key
      const max = rich && column.kind === 'period' ? rowMax(row) : 0
      const heat = max > 0 ? Math.abs(Number(value)) / max : null
      return withInsight(
        statement,
        row,
        column,
        <button
          type="button"
          className={`rp-cell-btn${isSelected ? ' is-selected' : ''}`}
          aria-label={`${row.label}: ${column.label}${column.sublabel ? ` ${column.sublabel}` : ''}`}
          onClick={() => onDrill(row.id, column)}
        >
          {text}
          {heat !== null ? <span className={`rp-heat rp-heat--${row.polarity}`} style={{ transform: `scaleX(${heat.toFixed(3)})` }} /> : null}
        </button>,
      )
    }

    const labelColumn: ColumnsType<DisplayRow>[number] = {
      key: 'label',
      fixed: 'left',
      width: compact ? 140 : 300,
      onCell: () => ({ className: 'rp-label-cell' }),
      title: (
        <div className="rp-th rp-th--label">
          <span>Статья</span>
          <small>{UNITS_LABEL[units]}</small>
        </div>
      ),
      render: (_: unknown, display: DisplayRow) => <LabelCell display={display} compact={compact} onToggle={onToggle} />,
    }
    const valueColumns: ColumnsType<DisplayRow> = visible.map((column, index) => ({
      key: column.key,
      align: 'right' as const,
      width: compact ? 96 : column.kind === 'delta' ? 96 : column.kind === 'period' ? 104 : 124,
      fixed: pinRight && index > lastPeriod ? ('right' as const) : undefined,
      title: (
        <div className={column.partial ? 'rp-th rp-th--partial' : 'rp-th'}>
          <span>{column.label}</span>
          {column.sublabel ? <small>{column.sublabel}</small> : null}
        </div>
      ),
      onCell: () => ({ className: column.partial ? 'rp-cell--partial' : undefined }),
      render: (_: unknown, display: DisplayRow) => renderValue(display, column),
    }))
    if (rich) {
      // Right after the periods, so it never sits among the totals pinned to the right.
      valueColumns.splice(lastPeriod + 1, 0, {
        key: 'trend',
        width: 110,
        title: (
          <div className="rp-th">
            <span>Тренд</span>
          </div>
        ),
        render: (_: unknown, display: DisplayRow) =>
          display.row && display.variant !== 'header' && display.row.kind !== 'ratio' ? (
            <MiniTrend values={periodColumns.map((column) => display.row?.values[column.key] ?? null)} polarity={display.row.polarity} />
          ) : null,
      })
    }
    return [labelColumn, ...valueColumns]
  }, [statement, units, selected, onDrill, onToggle, columnKeys, compact])

  return (
    <Table<DisplayRow>
      className={compact ? 'rp-table rp-table--compact' : 'rp-table'}
      rowKey="key"
      size="small"
      columns={columns}
      dataSource={rows}
      pagination={false}
      sticky
      scroll={{ x: 'max-content' }}
      rowClassName={(display) =>
        `rp-row rp-row--${display.variant}${display.row?.strong ? ' rp-row--strong' : ''}${
          flashRowId && display.row?.id === flashRowId ? ' rp-row--flash' : ''
        }`
      }
    />
  )
}
