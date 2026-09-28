import { CheckCircleOutlined, FileExcelOutlined, LinkOutlined } from '@ant-design/icons'
import { Alert, Button, Drawer, Empty, Input, Segmented, Skeleton } from 'antd'
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
import { CountUpAmount } from './CountUpAmount'
import { drillGroupings, groupDrillItems, MAX_STACK_SEGMENTS, type DrillGrouping } from './drillGroups'
import { DrillGroupCard, RequestDrillCard } from './RequestDrillCard'
import { PALETTE, pluralRu } from './reportVisuals'

export type DrillRequest = {
  template: string
  report: ReportKind
  /** The statement row behind the cell; null for a vendor panel, which spans every section. */
  row: StatementRow | null
  column: StatementColumn
  crumbs: string[]
  /** Only this vendor's requests. */
  vendor?: string
}

type Props = {
  request: DrillRequest | null
  units: Units
  onClose: () => void
  /** `periodIndex`: the amortization instalment this operation is, highlighted on the request card. */
  onOpenRequest: (requestId: number, periodIndex: number | null) => void
  /** Phone layout: the panel takes the whole screen. */
  fullScreen?: boolean
  /** Copies the page link (which opens this panel); the toolbar's «Ссылка» is under the panel's mask. */
  onCopyLink?: () => void
}

/** Backend maximum: most cells load in one page, so the composition can be shown. */
const PAGE_SIZE = 200
const colorAt = (index: number) => PALETTE[index % (PALETTE.length - 1)]
const anchorId = (index: number) => `rp-drill-card-${index}`

/** Backend money strings ("1800000.00") as whole tiyin: exact at any size, unlike Number(). */
function toCents(value: string | null | undefined): bigint {
  const text = (value ?? '').trim() || '0'
  const negative = text.startsWith('-')
  const [whole, fraction = ''] = text.replace('-', '').split('.')
  const cents = BigInt(whole || '0') * 100n + BigInt(`${fraction}00`.slice(0, 2))
  return negative ? -cents : cents
}

const sameMoney = (a: string | null | undefined, b: string | null | undefined) => toCents(a) === toCents(b)

function scrollToCard(id: string) {
  const card = document.getElementById(id)
  if (!card) return
  card.scrollIntoView?.({ behavior: 'smooth', block: 'center' })
  card.classList.add('is-flash')
  window.setTimeout(() => card.classList.remove('is-flash'), 1200)
}

export function StatementDrilldownDrawer({ request, units, onClose, onOpenRequest, fullScreen = false, onCopyLink }: Props) {
  const [items, setItems] = useState<StatementLineItem[]>([])
  const [total, setTotal] = useState<string | null>(null)
  const [count, setCount] = useState(0)
  const [page, setPage] = useState(1)
  const [query, setQuery] = useState('')
  const [grouping, setGrouping] = useState<DrillGrouping>('item')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)

  const cellKey = request
    ? `${request.template}|${request.report}|${request.row?.id ?? ''}|${request.vendor ?? ''}|${request.column.from}|${request.column.to}`
    : ''

  useEffect(() => {
    setQuery('')
    setPage(1)
    setItems([])
    setTotal(null)
    setCount(0)
    setGrouping('item')
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
        line: request.row?.id,
        vendor: request.vendor,
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
          line: request.row?.id,
          vendor: request.vendor,
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

  const cellValue = request?.row ? request.row.values[request.column.key] ?? null : null
  const showLine = request !== null && (request.row === null || request.row.kind === 'group')
  // Shares are only honest when every operation of the cell is loaded and nothing is filtered out.
  const complete = !query && total !== null && count > 0 && items.length === count
  const requestIds = new Set(items.filter((item) => item.source === 'request' && item.request_id !== null).map((item) => item.request_id))
  const vendors = new Set(items.map((item) => item.counterparty.trim().toLocaleLowerCase('ru')).filter(Boolean))
  const amortized = items.filter((item) => item.amortization).length
  const groups = complete ? groupDrillItems(items, grouping) : []

  let reconciliation
  if (request && !request.row) reconciliation = <b className="rp-muted">по всем разделам</b>
  else if (query) reconciliation = <b className="rp-muted">по всем операциям</b>
  else if (total === null) reconciliation = <b>…</b>
  else if (sameMoney(total, cellValue)) reconciliation = <b className="rp-drill-ok"><CheckCircleOutlined /> совпадает</b>
  else reconciliation = <b className="rp-drill-mismatch">расхождение</b>

  const cards =
    complete && grouping !== 'item'
      ? groups.map((group, index) => (
          <DrillGroupCard key={group.key} group={group} grouping={grouping} color={colorAt(index)} index={index} anchorId={anchorId(index)} />
        ))
      : (complete ? groups.map((group) => group.items[0]) : items).map((item, index) => (
          <RequestDrillCard
            key={item.entry_id}
            item={item}
            share={complete ? groups[index].share : null}
            color={colorAt(index)}
            index={index}
            anchorId={anchorId(index)}
            showLine={showLine}
            onOpenRequest={onOpenRequest}
          />
        ))

  return (
    <Drawer
      open={request !== null}
      onClose={onClose}
      width={fullScreen ? '100%' : 640}
      rootClassName="rp-drawer"
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
            <div>{`${request.vendor ?? request.row?.label ?? ''} · ${formatRange(request.column.from ?? '', request.column.to ?? '')}`}</div>
          </div>
        ) : null
      }
    >
      {request ? (
        <>
          <div className="rp-drill-stats">
            <div className="rp-drill-stat">
              <span>Сумма, сум</span>
              <b className="rp-num">{total === null ? '…' : <CountUpAmount value={total} format={formatExact} />}</b>
              {units !== 'sum' && request.row ? <span>{`в отчёте: ${formatAmount(cellValue, units)} ${UNITS_SHORT[units]}`}</span> : null}
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
          {complete ? (
            <div className="rp-drill-summary">
              <div className="rp-chips">
                {requestIds.size > 0 ? (
                  <span className="rp-chip">{`${requestIds.size} ${pluralRu(requestIds.size, 'заявка', 'заявки', 'заявок')}`}</span>
                ) : (
                  <span className="rp-chip">{`${count} ${pluralRu(count, 'строка', 'строки', 'строк')} банка и кассы`}</span>
                )}
                {requestIds.size > 0 && vendors.size > 0 ? (
                  <span className="rp-chip">{`${vendors.size} ${pluralRu(vendors.size, 'поставщик', 'поставщика', 'поставщиков')}`}</span>
                ) : null}
                {amortized > 0 ? <span className="rp-chip">{`${amortized} по графику амортизации`}</span> : null}
              </div>
              {groups.length > 1 ? (
                <div className="rp-stack" aria-hidden="true">
                  {groups.slice(0, MAX_STACK_SEGMENTS).map((group, index) => (
                    <i
                      key={group.key}
                      className="rp-widen"
                      title={`${group.label}: ${formatExact(String(group.amount))} сум`}
                      style={{ flexGrow: Math.max(group.amount, 0), background: colorAt(index), ['--rp-delay' as string]: `${index * 30}ms` }}
                      onClick={() => scrollToCard(anchorId(index))}
                    />
                  ))}
                </div>
              ) : null}
              {items.length > 1 ? (
                <Segmented
                  size="small"
                  value={grouping}
                  onChange={(value) => setGrouping(value as DrillGrouping)}
                  options={drillGroupings(request.column.months.length, requestIds.size > 0)}
                />
              ) : null}
            </div>
          ) : !query && count > items.length && items.length > 0 ? (
            <p className="rp-muted rp-drill-note">{`Показаны ${items.length} из ${count}. Загрузите все, чтобы увидеть состав.`}</p>
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
          <div className="rp-req-list">{cards}</div>
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
