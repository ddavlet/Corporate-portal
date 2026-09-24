import { Alert, Input, Select, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useEffect, useMemo, useState } from 'react'
import {
  getStatementLines,
  type ReportKind,
  type StatementLineItem,
  type StatementRow,
} from '../../../../lib/reportsApi'
import { describeReportError } from '../../../../lib/reportErrors'
import { formatDate, formatExact, formatRange } from '../../../../lib/reportsFormat'

type SourceFilter = '' | StatementLineItem['source']

type Filters = { scope: string; section: string; source: SourceFilter; query: string; page: number }

const cleanFilters = (scope: string): Filters => ({ scope, section: '', source: '', query: '', page: 1 })

type Props = {
  template: string
  report: ReportKind
  from: string
  to: string
  rows: StatementRow[]
  onOpenRequest: (requestId: number) => void
}

const PAGE_SIZE = 50
const SOURCE_OPTIONS: { value: SourceFilter; label: string }[] = [
  { value: '', label: 'Все источники' },
  { value: 'bank', label: 'Банк' },
  { value: 'cash', label: 'Касса' },
  { value: 'request', label: 'Заявки' },
  { value: 'invest_return', label: 'Инвест. выплаты' },
]
const SOURCE_LABELS: Record<StatementLineItem['source'], string> = {
  bank: 'Банк',
  cash: 'Касса',
  request: 'Заявка',
  invest_return: 'Инвест. выплата',
  unknown: 'Операция',
}

export function TransactionsWidget({ template, report, from, to, rows, onOpenRequest }: Props) {
  const sections = useMemo(
    () => rows.filter((row) => row.parent === null && row.drillable).map((row) => ({ value: row.id, label: row.label })),
    [rows],
  )
  const sectionLabels = useMemo(() => new Map(sections.map((section) => [section.value, section.label])), [sections])
  // A new report or period starts with clean filters: P&L and Cashflow have different sections,
  // and a page number from a longer list can point past the end of a shorter one.
  const scope = `${template}|${report}|${from}|${to}`
  const [stored, setStored] = useState<Filters>(() => cleanFilters(scope))
  const filters = stored.scope === scope ? stored : cleanFilters(scope)
  const { section, source, query, page } = filters
  const setFilters = (patch: Partial<Omit<Filters, 'scope'>>) => setStored({ ...filters, ...patch })
  const [items, setItems] = useState<StatementLineItem[]>([])
  const [count, setCount] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    getStatementLines(
      {
        template,
        report,
        line: section || undefined,
        source: source || undefined,
        from,
        to,
        q: query || undefined,
        page,
        pageSize: PAGE_SIZE,
      },
      controller.signal,
    )
      .then((res) => {
        setItems(res.items)
        setCount(res.count)
      })
      .catch((e: unknown) => {
        if ((e as { name?: string } | null)?.name === 'AbortError') return
        setError(describeReportError(e, 'Не удалось загрузить операции'))
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [template, report, from, to, section, source, query, page])

  const columns: ColumnsType<StatementLineItem> = [
    { title: 'Дата', dataIndex: 'date', width: 110, render: (value: string) => formatDate(value) },
    { title: 'Раздел', key: 'section', width: 200, render: (_: unknown, item) => sectionLabels.get(item.line_id.split('.')[0]) ?? '' },
    { title: 'Статья', dataIndex: 'line_label', width: 200 },
    {
      title: 'Источник',
      key: 'source',
      width: 160,
      render: (_: unknown, item) => (
        <Tag color={item.source === 'request' ? 'blue' : undefined}>
          {item.source === 'request' && item.request_id !== null ? `Заявка #${item.request_id}` : SOURCE_LABELS[item.source]}
        </Tag>
      ),
    },
    {
      title: 'Описание',
      key: 'title',
      render: (_: unknown, item) => (
        <div>
          <div>{item.title}</div>
          {item.counterparty ? <div className="rp-muted">{item.counterparty}</div> : null}
        </div>
      ),
    },
    { title: 'Поступление, сум', key: 'in', align: 'right', width: 150, render: (_: unknown, item) => (item.section === 'revenue' ? formatExact(item.amount) : '') },
    { title: 'Расход, сум', key: 'out', align: 'right', width: 150, render: (_: unknown, item) => (item.section === 'revenue' ? '' : formatExact(item.amount)) },
  ]

  return (
    <section className="rp-card">
      <header className="rp-card-head">
        <div>
          <h3>{`Операции · ${formatRange(from, to)}`}</h3>
          <small>Все строки, из которых собран отчёт. Фильтры здесь меняют только этот список.</small>
        </div>
      </header>
      <div className="rp-ops-filters">
        <Input.Search
          key={scope}
          allowClear
          aria-label="Поиск по операциям"
          placeholder="Описание, контрагент, № заявки"
          style={{ width: 320 }}
          onSearch={(value) => setFilters({ query: value.trim(), page: 1 })}
        />
        <Select
          aria-label="Раздел"
          style={{ width: 240 }}
          value={section}
          onChange={(value: string) => setFilters({ section: value, page: 1 })}
          options={[{ value: '', label: 'Все разделы' }, ...sections]}
        />
        <Select
          aria-label="Источник"
          style={{ width: 200 }}
          value={source}
          onChange={(value: SourceFilter) => setFilters({ source: value, page: 1 })}
          options={SOURCE_OPTIONS}
        />
      </div>
      {error ? <Alert type="error" showIcon message={error} style={{ margin: '0 16px 12px' }} /> : null}
      <Table<StatementLineItem>
        rowKey="entry_id"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={items}
        scroll={{ x: 'max-content' }}
        pagination={{ current: page, pageSize: PAGE_SIZE, total: count, showSizeChanger: false, onChange: (next) => setFilters({ page: next }) }}
        onRow={(item) =>
          item.source === 'request' && item.request_id !== null
            ? { onClick: () => onOpenRequest(item.request_id as number), style: { cursor: 'pointer' } }
            : {}
        }
      />
    </section>
  )
}
