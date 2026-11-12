import type { CSSProperties, ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Tag, Typography, theme, type GlobalToken } from 'antd'
import { ExclamationCircleOutlined } from '@ant-design/icons'
import { isPayedMissingLinkedExpense, type RequestExpenseLink } from '../../lib/requestExpense'
import { formatRequestDate } from '../../lib/requestUtils'
import { requestStatusColor, requestStatusLabel, type RequestStatusTone } from '../../lib/requestStatusLabels'
import { mobileToneTextColor } from './mobileActionsTheme'

/** A row of `GET /api/requests/` as the mobile feed reads it. */
export type RequestFeedRow = {
  id: number
  title: string
  amount: number | string
  currency: string
  status: string
  payment_type?: string
  category?: string
  vendor?: string
  requester?: number | null
  requester_username?: string | null
  submitted_at?: string | null
  expense_link?: RequestExpenseLink
}

export function formatRequestAmount(amount: number | string, currency: string): string {
  const value = Number(amount)
  const formatted = Number.isFinite(value) ? value.toLocaleString('ru-RU') : String(amount ?? '')
  return `${formatted} ${currency || ''}`.trim()
}

type CardFrameProps = {
  to: string
  highlighted?: boolean
  testId?: string
  children: ReactNode
}

/** The whole card is one link to the request; the payed-without-expense tint comes from `.m-card--payed-no-expense`. */
export function RequestMobileCardFrame({ to, highlighted = false, testId, children }: CardFrameProps) {
  const { token } = theme.useToken()
  return (
    <Link
      to={to}
      data-testid={testId}
      className={highlighted ? 'm-card m-card--payed-no-expense' : 'm-card'}
      style={{
        display: 'block',
        padding: '12px 16px',
        borderRadius: token.borderRadiusLG,
        border: `1px solid ${highlighted ? token.colorErrorBorder : token.colorBorderSecondary}`,
        // The highlight's tint comes from the class: an inline background would cover it.
        ...(highlighted ? {} : { background: token.colorBgContainer }),
        color: token.colorText,
        textDecoration: 'none',
        minWidth: 0,
      }}
    >
      {children}
    </Link>
  )
}

type CardBodyProps = {
  id: number
  statusTag: ReactNode
  title: string
  subtitle?: string | null
  amount: string
  meta: Array<string | null | undefined>
  note?: ReactNode
}

/** Number and status, title, counterparty, amount and a meta line: the layout of every request card of the feed. */
export function RequestMobileCardBody({ id, statusTag, title, subtitle, amount, meta, note }: CardBodyProps) {
  const { token } = theme.useToken()
  const metaLine = meta.filter((part): part is string => Boolean(part && part.trim())).join(' · ')
  return (
    <div style={{ display: 'grid', gap: 4, minWidth: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, minWidth: 0 }}>
        <Typography.Text style={{ color: token.colorTextSecondary, flexShrink: 0 }}>#{id}</Typography.Text>
        <div style={{ minWidth: 0, display: 'flex', justifyContent: 'flex-end' }}>{statusTag}</div>
      </div>
      <Typography.Text strong style={{ fontSize: 16, overflowWrap: 'anywhere' }}>
        {title || 'Без названия'}
      </Typography.Text>
      {subtitle ? (
        <Typography.Text className="m-ellipsis" style={{ display: 'block', color: token.colorTextSecondary }}>
          {subtitle}
        </Typography.Text>
      ) : null}
      <Typography.Text strong style={{ fontSize: 16 }}>
        {amount}
      </Typography.Text>
      {metaLine ? (
        // colorTextSecondary, not colorTextTertiary: 13 px text needs 4.5:1 on the card.
        <Typography.Text style={{ fontSize: 13, color: token.colorTextSecondary, overflowWrap: 'anywhere' }}>
          {metaLine}
        </Typography.Text>
      ) : null}
      {note ?? null}
    </div>
  )
}

/**
 * Colours of a status tag: the antd presets keep the text at shade 6 (#52c41a on #f6ffed is below 4.5:1), so the text
 * takes the darker shade of mobileToneTextColor and the fill and border stay the preset's shades 1 and 3.
 */
function statusToneStyle(tone: RequestStatusTone, token: GlobalToken): CSSProperties {
  switch (tone) {
    case 'success':
      return { color: mobileToneTextColor('success', token), backgroundColor: token.colorSuccessBg, borderColor: token.colorSuccessBorder }
    case 'processing':
      return { color: mobileToneTextColor('info', token), backgroundColor: token.colorInfoBg, borderColor: token.colorInfoBorder }
    case 'error':
      return { color: mobileToneTextColor('error', token), backgroundColor: token.colorErrorBg, borderColor: token.colorErrorBorder }
    default:
      return { color: token.colorText }
  }
}

/** A status tag of the mobile screens in the given tone; `data-tone` names it for tests. */
export function RequestStatusToneTag({ tone, children }: { tone: RequestStatusTone; children: ReactNode }) {
  const { token } = theme.useToken()
  return (
    <Tag
      data-tone={tone}
      className="m-ellipsis"
      style={{ marginInlineEnd: 0, maxWidth: '100%', ...statusToneStyle(tone, token) }}
    >
      {children}
    </Tag>
  )
}

export function RequestStatusTag({ status }: { status: string }) {
  return (
    <RequestStatusToneTag tone={requestStatusColor(status)}>{requestStatusLabel(status, { context: 'feed' })}</RequestStatusToneTag>
  )
}

/**
 * Card of the requests feed: number, human status, title, vendor, amount with currency, then type · requester · date.
 * A payed request whose expense was not found in the cash desk or the bank is tinted red and says so.
 */
export function RequestMobileCardWidget({ request }: { request: RequestFeedRow }) {
  const { token } = theme.useToken()
  const payedNoExpense = isPayedMissingLinkedExpense(request)
  const requester = request.requester_username || (request.requester ? `#${request.requester}` : null)
  return (
    <RequestMobileCardFrame to={`/requests/${request.id}`} highlighted={payedNoExpense} testId={`request-card-${request.id}`}>
      <RequestMobileCardBody
        id={request.id}
        statusTag={<RequestStatusTag status={request.status} />}
        title={request.title}
        subtitle={request.vendor}
        amount={formatRequestAmount(request.amount, request.currency)}
        meta={[request.payment_type, requester, request.submitted_at ? formatRequestDate(request.submitted_at) : null]}
        note={
          payedNoExpense ? (
            // Dark red text: colorError (#ff4d4f) on the red tint is about 2.7:1, red 7 about 5:1; the icon keeps colorError.
            <Typography.Text data-testid="payed-no-expense-note" style={{ color: mobileToneTextColor('error', token), fontSize: 13 }}>
              <ExclamationCircleOutlined aria-hidden style={{ color: token.colorError }} /> Оплачена, но расход не найден
            </Typography.Text>
          ) : null
        }
      />
    </RequestMobileCardFrame>
  )
}
