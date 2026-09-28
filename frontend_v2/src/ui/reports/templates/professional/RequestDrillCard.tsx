import { Button, Skeleton, Tag } from 'antd'
import { useEffect, useState } from 'react'
import { getReportRequestDetail, type StatementLineItem } from '../../../../lib/reportsApi'
import { describeReportError } from '../../../../lib/reportErrors'
import { formatExact } from '../../../../lib/reportsFormat'
import type { RequestDetail } from '../../../requests/RequestDetailModal'
import type { DrillGroup, DrillGrouping } from './drillGroups'
import { initialsOf, pluralRu } from './reportVisuals'

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
const DECISIONS: Record<string, string> = { approved: 'Одобрено', rejected: 'Отклонено', pending: 'Ожидает' }
const DECISION_COLORS: Record<string, string> = { approved: 'green', rejected: 'red', pending: 'orange' }
const STEP_TYPES: Record<string, string> = { approval: 'Согласование', payment: 'Выплата' }

export function sourceTag(item: StatementLineItem): string {
  if (item.source === 'request' && item.request_id !== null) return `Заявка #${item.request_id}`
  if (item.source === 'bank') return CHANNEL_LABELS[item.channel] ?? 'Банк'
  if (item.source === 'cash') return 'Касса'
  if (item.source === 'invest_return') return 'Инвест. выплата'
  return 'Операция'
}

const percent = (share: number) => `${(share * 100).toFixed(1).replace('.', ',')}%`
const shortDate = (iso: string) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}`
function dateTime(iso?: string | null): string {
  if (!iso) return ''
  const parsed = new Date(iso)
  if (Number.isNaN(parsed.getTime())) return ''
  return new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Tashkent' }).format(parsed)
}

type CardProps = {
  item: StatementLineItem
  /** Share of the panel sum; null while the list is partial or filtered. */
  share: number | null
  color: string
  index: number
  anchorId: string
  showLine: boolean
  onOpenRequest: (requestId: number, periodIndex: number | null) => void
}

/** One operation of the panel. A request card opens in place: approvals load once, and a button opens the request. */
export function RequestDrillCard({ item, share, color, index, anchorId, showLine, onOpenRequest }: CardProps) {
  const requestId = item.source === 'request' ? item.request_id : null
  const [open, setOpen] = useState(false)
  const [detail, setDetail] = useState<RequestDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (!open || requestId === null || detail) return
    let alive = true
    setLoading(true)
    setError(null)
    getReportRequestDetail(requestId)
      .then((json) => {
        if (alive) setDetail(json as RequestDetail)
      })
      .catch((e: unknown) => {
        if (alive) setError(describeReportError(e, 'Не удалось загрузить детали'))
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
    // `detail` is left out on purpose: once loaded it is kept, and closing the card must not reload it.
  }, [open, requestId, attempt])

  const toggle = () => {
    if (requestId !== null) setOpen((value) => !value)
  }
  const approvals = [...(detail?.approvals ?? [])].sort((a, b) => a.step - b.step)
  const amortization = item.amortization
  return (
    <article
      id={anchorId}
      className="rp-req rp-reveal"
      style={{ ['--rp-delay' as string]: `${Math.min(index, 12) * 40}ms`, ['--rp-dot' as string]: color }}
    >
      <div
        className={`rp-req-top${requestId !== null ? ' is-clickable' : ''}`}
        role={requestId !== null ? 'button' : undefined}
        tabIndex={requestId !== null ? 0 : undefined}
        aria-expanded={requestId !== null ? open : undefined}
        onClick={toggle}
        onKeyDown={(event) => {
          if (requestId !== null && (event.key === 'Enter' || event.key === ' ')) {
            event.preventDefault()
            toggle()
          }
        }}
      >
        <div className="rp-req-head">
          <span className="rp-req-id">{sourceTag(item)}</span>
          <span className="rp-req-title">{item.title}</span>
        </div>
        <div className="rp-req-sum rp-num">
          {formatExact(item.amount)}
          <small>{share !== null ? `${percent(share)} суммы` : 'сум'}</small>
        </div>
      </div>
      <div className="rp-req-meta">
        <span>{shortDate(item.date)}</span>
        {showLine ? <span>{item.line_label}</span> : null}
        {item.counterparty ? (
          <span>
            {item.source === 'request' ? 'Поставщик: ' : ''}
            <b>{item.counterparty}</b>
          </span>
        ) : null}
        {item.author ? (
          <span className="rp-req-author">
            <span className="rp-avatar rp-avatar--sm">{initialsOf(item.author)}</span>
            <span>{item.author}</span>
          </span>
        ) : null}
      </div>
      {share !== null ? (
        <div className="rp-req-share">
          <i className="rp-widen" style={{ width: `${Math.max(1, share * 100)}%` }} />
        </div>
      ) : null}
      {amortization ? (
        <div className="rp-amort">
          <span className="rp-amort-steps" aria-hidden="true">
            {Array.from({ length: amortization.count }, (_, step) => (
              <i key={step} className={step + 1 < amortization.index ? 'is-paid' : step + 1 === amortization.index ? 'is-current' : ''} />
            ))}
          </span>
          <span>{`Платёж ${amortization.index} из ${amortization.count} по графику`}</span>
        </div>
      ) : null}
      {open && requestId !== null ? (
        <div className="rp-req-more">
          {loading ? <Skeleton active title={false} paragraph={{ rows: 2 }} /> : null}
          {error ? (
            <div className="rp-widget-error">
              <span>{error}</span>
              <Button size="small" onClick={() => setAttempt((value) => value + 1)}>
                Повторить
              </Button>
            </div>
          ) : null}
          {detail ? (
            <>
              {approvals.length ? (
                <ol className="rp-timeline">
                  {approvals.map((approval) => (
                    <li key={approval.id}>
                      <span>{`${STEP_TYPES[approval.step_type] ?? approval.step_type} · шаг ${approval.step}`}</span>
                      <span className="rp-muted">{[approval.approver_username, dateTime(approval.decided_at)].filter(Boolean).join(' · ')}</span>
                      <Tag color={DECISION_COLORS[approval.decision] ?? 'default'}>{DECISIONS[approval.decision] ?? approval.decision}</Tag>
                    </li>
                  ))}
                </ol>
              ) : null}
              <div className="rp-req-meta">
                {detail.payment_type ? <span>{`Оплата: ${detail.payment_type}`}</span> : null}
                <span>{`Файлы: ${detail.attachments?.length ?? 0}`}</span>
                <span>{`Точно: ${formatExact(item.amount)} сум`}</span>
              </div>
            </>
          ) : null}
          <div className="rp-req-actions">
            <Button type="primary" size="small" onClick={() => onOpenRequest(requestId, amortization?.index ?? null)}>
              {`Открыть заявку #${requestId}`}
            </Button>
          </div>
        </div>
      ) : null}
    </article>
  )
}

type GroupProps = { group: DrillGroup; grouping: DrillGrouping; color: string; index: number; anchorId: string }

/** A vendor or a month of the panel: its sum, share and largest operations. */
export function DrillGroupCard({ group, grouping, color, index, anchorId }: GroupProps) {
  const shown = [...group.items].sort((a, b) => Number(b.amount) - Number(a.amount)).slice(0, 6)
  const rest = group.items.length - shown.length
  return (
    <article
      id={anchorId}
      className="rp-req rp-reveal"
      style={{ ['--rp-delay' as string]: `${Math.min(index, 12) * 40}ms`, ['--rp-dot' as string]: color }}
    >
      <div className="rp-req-top">
        <div className="rp-req-group">
          {grouping === 'vendor' ? (
            <span className="rp-avatar" style={{ background: color }}>
              {initialsOf(group.label)}
            </span>
          ) : null}
          <div>
            <div className="rp-req-title">{group.label}</div>
            <div className="rp-req-meta">{`${group.items.length} ${pluralRu(group.items.length, 'операция', 'операции', 'операций')}`}</div>
          </div>
        </div>
        <div className="rp-req-sum rp-num">
          {formatExact(String(group.amount))}
          <small>{`${percent(group.share)} суммы`}</small>
        </div>
      </div>
      <div className="rp-req-share">
        <i className="rp-widen" style={{ width: `${Math.max(1, group.share * 100)}%` }} />
      </div>
      <div className="rp-req-lines">
        {shown.map((item) => (
          <div key={item.entry_id}>
            <span>{`${item.request_id !== null ? `#${item.request_id} · ` : ''}${item.title} · ${shortDate(item.date)}`}</span>
            <b className="rp-num">{formatExact(item.amount)}</b>
          </div>
        ))}
        {rest > 0 ? <div className="rp-muted">{`и ещё ${rest}`}</div> : null}
      </div>
    </article>
  )
}
