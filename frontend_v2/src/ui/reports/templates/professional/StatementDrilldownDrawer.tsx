import { CheckCircleOutlined, FileExcelOutlined, LinkOutlined } from '@ant-design/icons'
import { Alert, Button, Drawer, Empty, Input, Skeleton, Tag } from 'antd'
import { useEffect, useState } from 'react'
import {
  downloadLinesXlsx,
  getStatementLines,
  type ReportKind,
  type StatementColumn,
  type StatementLineItem,
  type StatementRow,
} from '../../../../lib/reportsApi'
import { formatAmount, formatExact, formatRange, UNITS_SHORT, type Units } from '../../../../lib/reportsFormat'
import { notifyApiError } from '../../../../lib/apiNotify'
import { describeReportError } from '../../../../lib/reportErrors'
import { saveFile } from '../../../../lib/saveFile'

export type DrillRequest = {
  template: string
  report: ReportKind
  row: StatementRow
  column: StatementColumn
  crumbs: string[]
}

type Props = {
  request: DrillRequest | null
  units: Units
  onClose: () => void
  onOpenRequest: (requestId: number) => void
  /** Phone layout: the panel takes the whole screen. */
  fullScreen?: boolean
  /** Copies the page link (which opens this panel); the toolbar's «Ссылка» is under the panel's mask. */
  onCopyLink?: () => void
}

/** Backend maximum: most cells load in one page, so the breakdown can be shown. */
const PAGE_SIZE = 200
const CHANNEL_LABELS: Record<string, string> = {
  CLICK: 'Click',
  PAYME: 'Payme',
  UZUM: 'Uzum',
  UZCARD: 'Uzcard',
  HUMO: 'Humo',
  IPS: 'IPS',
  VISA: 'Visa',
  CASH_DEPOSIT: 'Взнос наличных',
  CLIENT_PAYMENT: 'Оплата от клиента',
  OTHER: 'Прочие поступления',
}

function sourceTag(item: StatementLineItem): string {
  if (item.source === 'request' && item.request_id !== null) return `Заявка #${item.request_id}`
  if (item.source === 'bank') return CHANNEL_LABELS[item.channel] ?? 'Банк'
  if (item.source === 'cash') return 'Касса'
  if (item.source === 'invest_return') return 'Инвест. выплата'
  return 'Операция'
}

function mixLabel(item: StatementLineItem, byLine: boolean): string {
  if (byLine) return item.line_label
  if (item.source === 'bank') return CHANNEL_LABELS[item.channel] ?? 'Банк'
  if (item.source === 'request') return item.amortization ? 'Амортизация по графику' : 'Разовые заявки'
  return item.line_label
}

function breakdown(items: StatementLineItem[], byLine: boolean): { label: string; share: number }[] {
  const totals = new Map<string, number>()
  let sum = 0
  for (const item of items) {
    const amount = Number(item.amount)
    sum += amount
    const label = mixLabel(item, byLine)
    totals.set(label, (totals.get(label) ?? 0) + amount)
  }
  if (totals.size < 2 || sum <= 0) return []
  return [...totals.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6)
    .map(([label, value]) => ({ label, share: value / sum }))
}

/** Backend money strings ("1800000.00") as whole tiyin: exact at any size, unlike Number(). */
function toCents(value: string | null | undefined): bigint {
  const text = (value ?? '').trim() || '0'
  const negative = text.startsWith('-')
  const [whole, fraction = ''] = text.replace('-', '').split('.')
  const cents = BigInt(whole || '0') * 100n + BigInt(`${fraction}00`.slice(0, 2))
  return negative ? -cents : cents
}

const sameMoney = (a: string | null | undefined, b: string | null | undefined) => toCents(a) === toCents(b)

function TransactionLine({ item, showLine, onOpenRequest }: { item: StatementLineItem; showLine: boolean; onOpenRequest: (id: number) => void }) {
  const requestId = item.source === 'request' ? item.request_id : null
  const open = () => {
    if (requestId !== null) onOpenRequest(requestId)
  }
  return (
    <div
      className={`rp-tx${requestId !== null ? ' is-clickable' : ''}`}
      role={requestId !== null ? 'button' : undefined}
      tabIndex={requestId !== null ? 0 : undefined}
      onClick={requestId !== null ? open : undefined}
      onKeyDown={requestId !== null ? (event) => { if (event.key === 'Enter') open() } : undefined}
    >
      <div className="rp-tx-date">{`${item.date.slice(8, 10)}.${item.date.slice(5, 7)}`}</div>
      <div>
        <div className="rp-tx-title">{item.title}</div>
        <div className="rp-tx-sub">
          {showLine ? <span>{item.line_label}</span> : null}
          <Tag color={item.source === 'request' ? 'blue' : undefined}>{sourceTag(item)}</Tag>
          {item.counterparty ? <span>{item.counterparty}</span> : null}
          {item.amortization ? <Tag color="gold">{`амортизация ${item.amortization.index} из ${item.amortization.count}`}</Tag> : null}
        </div>
      </div>
      <div className="rp-tx-amount">{formatExact(item.amount)}</div>
    </div>
  )
}

export function StatementDrilldownDrawer({ request, units, onClose, onOpenRequest, fullScreen = false, onCopyLink }: Props) {
  const [items, setItems] = useState<StatementLineItem[]>([])
  const [total, setTotal] = useState<string | null>(null)
  const [count, setCount] = useState(0)
  const [page, setPage] = useState(1)
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)

  const cellKey = request ? `${request.template}|${request.report}|${request.row.id}|${request.column.from}|${request.column.to}` : ''

  useEffect(() => {
    setQuery('')
    setPage(1)
    setItems([])
    setTotal(null)
    setCount(0)
  }, [cellKey])

  useEffect(() => {
    if (!request || !request.column.from || !request.column.to) return
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    getStatementLines(
      {
        template: request.template,
        report: request.report,
        line: request.row.id,
        from: request.column.from,
        to: request.column.to,
        q: query || undefined,
        page,
        pageSize: PAGE_SIZE,
      },
      controller.signal,
    )
      .then((res) => {
        setItems((previous) => (page === 1 ? res.items : [...previous, ...res.items]))
        setTotal(res.total)
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
    // `request` is identified by cellKey on purpose: its object identity changes on every parent render.
  }, [cellKey, query, page])

  const exportLines = async () => {
    if (!request?.column.from || !request.column.to) return
    setExporting(true)
    try {
      saveFile(
        await downloadLinesXlsx({
          template: request.template,
          report: request.report,
          line: request.row.id,
          from: request.column.from,
          to: request.column.to,
          q: query || undefined,
        }),
      )
    } catch (e: unknown) {
      notifyApiError(describeReportError(e, 'Не удалось выгрузить Excel'))
    } finally {
      setExporting(false)
    }
  }

  const cellValue = request ? request.row.values[request.column.key] ?? null : null
  const byLine = request?.row.kind === 'group'
  // Shares are only honest when every operation of the cell is loaded.
  const mix = !query && items.length === count ? breakdown(items, byLine) : []

  let reconciliation
  if (query) reconciliation = <b className="rp-muted">по всем операциям</b>
  else if (total === null) reconciliation = <b>…</b>
  else if (sameMoney(total, cellValue)) reconciliation = <b className="rp-drill-ok"><CheckCircleOutlined /> совпадает</b>
  else reconciliation = <b className="rp-drill-mismatch">расхождение</b>

  return (
    <Drawer
      open={request !== null}
      onClose={onClose}
      width={fullScreen ? '100%' : 620}
      extra={
        onCopyLink ? (
          <Button icon={<LinkOutlined />} onClick={onCopyLink}>
            Ссылка
          </Button>
        ) : null
      }
      title={
        request ? (
          <div>
            <div className="rp-drill-crumbs">{request.crumbs.join(' › ')}</div>
            <div>{`${request.row.label} · ${formatRange(request.column.from ?? '', request.column.to ?? '')}`}</div>
          </div>
        ) : null
      }
    >
      {request ? (
        <>
          <div className="rp-drill-stats">
            <div className="rp-drill-stat">
              <span>Сумма, сум</span>
              <b>{total === null ? '…' : formatExact(total)}</b>
              {units !== 'sum' ? <span>{`в отчёте: ${formatAmount(cellValue, units)} ${UNITS_SHORT[units]}`}</span> : null}
            </div>
            <div className="rp-drill-stat">
              <span>Операций</span>
              <b>{count}</b>
            </div>
            <div className="rp-drill-stat">
              <span>Сверка с отчётом</span>
              {reconciliation}
            </div>
          </div>
          {mix.length ? (
            <div className="rp-mix">
              {mix.map((part) => (
                <div key={part.label} className="rp-mix-row">
                  <span>{part.label}</span>
                  <div className="rp-mix-bar"><i style={{ width: `${Math.max(2, part.share * 100).toFixed(1)}%` }} /></div>
                  <b>{`${(part.share * 100).toFixed(1).replace('.', ',')}%`}</b>
                </div>
              ))}
            </div>
          ) : null}
          <div className="rp-drill-tools">
            <Input.Search
              allowClear
              aria-label="Поиск по операциям ячейки"
              placeholder="Описание, контрагент, № заявки"
              onSearch={(value) => {
                setPage(1)
                setQuery(value.trim())
              }}
            />
            <Button icon={<FileExcelOutlined />} loading={exporting} onClick={() => void exportLines()}>
              Excel
            </Button>
          </div>
          {error ? <Alert type="error" showIcon message={error} /> : null}
          {loading && items.length === 0 ? <Skeleton active /> : null}
          {!loading && !error && items.length === 0 ? <Empty description="Операций нет" image={Empty.PRESENTED_IMAGE_SIMPLE} /> : null}
          <div>
            {items.map((line) => (
              <TransactionLine key={line.entry_id} item={line} showLine={byLine} onOpenRequest={onOpenRequest} />
            ))}
          </div>
          {items.length < count ? (
            <Button style={{ marginTop: 12 }} loading={loading} onClick={() => setPage((current) => current + 1)}>
              Показать ещё
            </Button>
          ) : null}
          {total !== null ? (
            <div className="rp-drill-total">
              <span>{query ? `Найдено ${count}` : 'Итого'}</span>
              <span>{`${formatExact(total)} сум`}</span>
            </div>
          ) : null}
        </>
      ) : null}
    </Drawer>
  )
}
