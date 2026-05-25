import { useState } from 'react'
import type { ReactNode } from 'react'
import { Alert, Button, Card, Collapse, Descriptions, Divider, Modal, Skeleton, Space, Tag, Typography, message } from 'antd'
import { apiFetch } from '../../lib/api'
import type { RequestAttachment, RequestComment } from '../../lib/api'
import { buildRequestFileRows } from '../../lib/requestFiles'
import { linkedExpenseFrontendPath, linkedExpenseLabel } from '../../lib/requestExpense'
import type { RequestReturnTo } from '../../lib/requestNavigation'
import { formatRequestDate, formatRequestBillingMonth, getRequestStatusColor } from '../../lib/requestUtils'
import {
  RequestDetailFieldValue,
  RequestEntityLink,
  REQUEST_FORM_CONFIG_PATH,
  contractsPath,
  usersSettingsPath,
  vendorDirectoryPath,
} from './RequestEntityLink'
import { RequestCommentsSection } from './RequestCommentsSection'

export type ApprovalItem = {
  id: number
  step: number
  step_type: string
  payment_action_mode?: 'callback' | 'webapp' | string | null
  payment_webapp_url?: string | null
  decision: string
  comment?: string | null
  decided_at?: string | null
  approver_user?: number
  approver_username?: string | null
  approver_tg_id?: string | number | null
  approver_tg_from_id?: string | number | null
  message_id?: number | null
  message_sent?: boolean
  message_sent_at?: string | null
}

export type RequestDetail = {
  id: number
  title: string
  description: string
  amount: number
  currency: string
  status: string
  urgency: string
  payment_type: string
  category: string
  vendor: string
  vendor_ref?: number | null
  contract_ref?: number | null
  contract_ref_info?: {
    id: number
    contract_number: string
    date_from: string | null
    date_to: string | null
  } | null
  contract_label?: string | null
  company_payer?: string
  payment_purpose?: string
  file_link?: string | null
  attachments?: RequestAttachment[]
  requester: number | null
  requester_username?: string | null
  created_at?: string
  created_by?: number | null
  created_by_username?: string | null
  submitted_at: string
  billing_date: string
  payed_at?: number | null
  expense_id?: string | null
  expense_year?: number | null
  expense_month?: number | null
  expense_day?: number | null
  expense_link?: {
    module?: string
    expense_type?: string
    id?: number | string
    doc_id?: string
    url?: string | null
  } | null
  is_amortized?: boolean
  amortization_months?: number
  amortization_start_date?: string | null
  amortization_schedule?: Array<{
    period_index: number
    period_month: string
    monthly_amount: string
  }>
  approvals: ApprovalItem[]
  comments?: RequestComment[]
}

const dateTimeFormatterTashkent = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  timeZone: 'Asia/Tashkent',
})

function formatDateTime(value?: string | null): string {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '-'
  return dateTimeFormatterTashkent.format(parsed)
}

/** В БД часто хранится как YYYYMMDD (например 20260103). */
function formatPayedAt(value?: number | null): string {
  if (value == null) return '-'
  const n = Number(value)
  if (!Number.isFinite(n)) return String(value)
  const s = String(Math.abs(Math.trunc(n)))
  if (s.length === 8 && /^\d{8}$/.test(s)) {
    const y = s.slice(0, 4)
    const mo = s.slice(4, 6)
    const d = s.slice(6, 8)
    return `${d}.${mo}.${y}`
  }
  return String(value)
}

function formatContractPeriod(info: RequestDetail['contract_ref_info']): string {
  if (!info) return ''
  const from = (info.date_from || '').trim()
  const to = (info.date_to || '').trim()
  if (from && to) return `${from} - ${to}`
  if (from) return from
  return ''
}


function decisionKey(decision?: string | null) {
  return String(decision || '').toLowerCase()
}

function getDecisionColor(decision?: string | null): string | undefined {
  const key = decisionKey(decision)
  if (key === 'approved') return 'green'
  if (key === 'rejected') return 'red'
  if (key === 'pending') return 'orange'
  return 'default'
}

function translateDecision(decision?: string | null): string {
  const key = decisionKey(decision)
  if (key === 'approved') return 'Одобрено'
  if (key === 'rejected') return 'Отклонено'
  if (key === 'pending') return 'Ожидает'
  return String(decision || '').toUpperCase()
}

function translateStepType(stepType?: string | null): string {
  const key = String(stepType || '').toLowerCase()
  if (key === 'approval') return 'согласование'
  if (key === 'payment') return 'выплата'
  return stepType || ''
}

function renderApprovalGroup(
  title: string,
  items: ApprovalItem[],
  options?: { returnTo?: RequestReturnTo; variant?: 'default' | 'telegram' },
) {
  const returnTo = options?.returnTo
  const isTg = options?.variant === 'telegram'
  return (
    <Space direction="vertical" size={8} style={{ display: 'flex' }}>
      <Typography.Text strong>{title}</Typography.Text>
      {items.length === 0 ? (
        <Typography.Text type="secondary">Нет записей</Typography.Text>
      ) : (
        items.map((item) => (
          <Card key={item.id} size="small">
            <Space direction="vertical" size={4} style={{ display: 'flex' }}>
              <Space wrap>
                <Typography.Text type="secondary">{`Этап ${item.step} · ${translateStepType(item.step_type)}`}</Typography.Text>
                <Typography.Text>{item.approver_username || 'Согласующий не определён'}</Typography.Text>
                <Tag color={getDecisionColor(item.decision)}>{translateDecision(item.decision)}</Tag>
              </Space>
              {item.decision !== 'pending' ? (
                <Typography.Text
                  type="secondary"
                  style={{
                    display: '-webkit-box',
                    WebkitLineClamp: 3,
                    WebkitBoxOrient: 'vertical',
                    overflow: 'hidden',
                  }}
                >
                  {item.comment || 'Без комментария'}
                </Typography.Text>
              ) : null}
              <Typography.Text type="secondary">Дата решения: {formatRequestDate(item.decided_at)}</Typography.Text>
              {!isTg ? (
                <Collapse
                  ghost
                  size="small"
                  items={[{
                    key: 'tech',
                    label: <Typography.Text type="secondary" style={{ fontSize: 11 }}>Детали</Typography.Text>,
                    children: (
                      <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                        approval id: {item.id}
                        {item.message_id != null ? ` · message_id: ${item.message_id}` : ''}
                        {item.message_sent != null ? ` · message_sent: ${item.message_sent ? 'да' : 'нет'}` : ''}
                        {item.message_sent_at ? ` · sent_at: ${formatDateTime(item.message_sent_at)}` : ''}
                        {item.approver_tg_id != null && item.approver_tg_id !== ''
                          ? ` · tg_id: ${item.approver_tg_id}`
                          : ''}
                        {item.approver_tg_from_id != null && item.approver_tg_from_id !== ''
                          ? ` · tg_from: ${item.approver_tg_from_id}`
                          : ''}
                      </Typography.Text>
                    ),
                  }]}
                />
              ) : null}
            </Space>
          </Card>
        ))
      )}
    </Space>
  )
}

type RequestDetailModalProps = {
  open: boolean
  onCancel: () => void
  detail: RequestDetail | null
  loading?: boolean
  error?: string | null
  actions?: React.ReactNode
  /** Куда вернуть пользователя из связанных документов/справочников. */
  returnTo?: RequestReturnTo
}

export function RequestDetailModal({
  open,
  onCancel,
  detail,
  loading = false,
  error = null,
  actions = null,
  returnTo,
}: RequestDetailModalProps) {
  return (
    <Modal open={open} title={detail ? `Заявка #${detail.id}` : 'Заявка'} footer={null} onCancel={onCancel} width={760}>
      <RequestDetailContent detail={detail} loading={loading} error={error} actions={actions} returnTo={returnTo} />
    </Modal>
  )
}

type RequestDetailContentProps = {
  detail: RequestDetail | null
  loading?: boolean
  error?: string | null
  actions?: React.ReactNode
  /** Компактные блоки для Telegram WebApp на телефоне */
  variant?: 'default' | 'telegram'
  returnTo?: RequestReturnTo
  onCommentAdded?: () => Promise<void>
}

function TgDetailRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="tg-detail-row">
      <span className="tg-detail-label">{label}</span>
      <div className="tg-detail-value">{children}</div>
    </div>
  )
}

export function RequestDetailContent({
  detail,
  loading = false,
  error = null,
  actions = null,
  variant = 'default',
  returnTo,
  onCommentAdded,
}: RequestDetailContentProps) {
  const approvals = detail?.approvals || []
  const amortizationSchedule = detail?.amortization_schedule || []
  const approvedApprovals = approvals.filter((a) => decisionKey(a.decision) === 'approved')
  const rejectedApprovals = approvals.filter((a) => decisionKey(a.decision) === 'rejected')
  const pendingApprovals = approvals.filter((a) => decisionKey(a.decision) === 'pending')
  const linkedExpensePath = linkedExpenseFrontendPath(detail?.expense_link ?? null, {
    telegram: variant === 'telegram',
  })
  const linkedExpenseText = linkedExpenseLabel(detail?.expense_link ?? null)
  const createdByName =
    detail?.created_by_username?.trim() ||
    (detail?.created_by != null ? `Пользователь #${detail.created_by}` : null)
  const requesterName =
    detail?.requester_username?.trim() ||
    (detail?.requester != null ? `Пользователь #${detail.requester}` : null)
  const vendorName = detail?.vendor?.trim() || null
  const fileRows = detail ? buildRequestFileRows(detail) : []

  const [fileBusy, setFileBusy] = useState(false)

  const openFileViaAuthBlob = async (fileUrl: string) => {
    setFileBusy(true)
    try {
      const res = await apiFetch(fileUrl)
      if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new Error(text || `HTTP ${res.status}`)
      }

      const blob = await res.blob()
      const objectUrl = URL.createObjectURL(blob)

      // Avoid popup blockers: open immediately, then set location after fetch.
      const w = window.open('', '_blank', 'noopener,noreferrer')
      if (!w) {
        URL.revokeObjectURL(objectUrl)
        throw new Error('Не удалось открыть файл: попап-блокировка.')
      }

      w.location.href = objectUrl
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 120_000)
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Не удалось открыть файл')
    } finally {
      setFileBusy(false)
    }
  }

  return (
    <>
      {actions ? <div style={{ marginBottom: 12, maxWidth: '100%' }}>{actions}</div> : null}
      {detail && variant === 'telegram' ? (
        <div>
          <div className="tg-detail-hero">
            <Typography.Title level={4} style={{ margin: 0, fontSize: 18, lineHeight: 1.35 }}>
              {detail.payment_purpose?.trim() || detail.title?.trim() || `Заявка #${detail.id}`}
            </Typography.Title>
            <Typography.Text type="secondary" style={{ display: 'block', marginTop: 4 }}>
              Заявка #{detail.id}
            </Typography.Text>
            <div style={{ marginTop: 8 }}>
              <Tag color={getRequestStatusColor(detail.status)}>{detail.status}</Tag>
            </div>
            <div className="tg-detail-amount">
              {`${Number(detail.amount).toLocaleString('ru-RU')} ${detail.currency}`}
            </div>
          </div>
          <TgDetailRow label="Создано">{formatDateTime(detail.created_at)}</TgDetailRow>
          <TgDetailRow label="Кем создано">{createdByName || '—'}</TgDetailRow>
          <TgDetailRow label="Компания-плательщик">{detail.company_payer?.trim() || '—'}</TgDetailRow>
          <TgDetailRow label="Тип оплаты">{detail.payment_type || '—'}</TgDetailRow>
          <TgDetailRow label="Срочность">{detail.urgency || '—'}</TgDetailRow>
          <TgDetailRow label="Категория">{detail.category || '—'}</TgDetailRow>
          <TgDetailRow label="Поставщик">{vendorName || '—'}</TgDetailRow>
          {detail.contract_ref_info ? (
            <>
              <TgDetailRow label="Договор">{detail.contract_ref_info.contract_number || '—'}</TgDetailRow>
              <TgDetailRow label="Период договора">{formatContractPeriod(detail.contract_ref_info) || '—'}</TgDetailRow>
            </>
          ) : null}
          <TgDetailRow label="Назначение платежа">{detail.payment_purpose || '—'}</TgDetailRow>
          {detail.description?.trim() && detail.description.trim() !== (detail.payment_purpose || '').trim() ? (
            <TgDetailRow label="Описание">{detail.description}</TgDetailRow>
          ) : null}
          <TgDetailRow label="Заявитель">{requesterName || '—'}</TgDetailRow>
          <TgDetailRow label="Отправлено">{formatDateTime(detail.submitted_at)}</TgDetailRow>
          <TgDetailRow label="Дата биллинга">{formatRequestBillingMonth(detail.billing_date)}</TgDetailRow>
          <TgDetailRow label="Амортизация">{detail.is_amortized ? `Да (${detail.amortization_months || 0} мес.)` : 'Нет'}</TgDetailRow>
          <TgDetailRow label="Старт амортизации">{formatRequestBillingMonth(detail.amortization_start_date || null)}</TgDetailRow>
          {amortizationSchedule.length ? (
            <TgDetailRow label="График амортизации">
              <Space direction="vertical" size={4} style={{ display: 'flex' }}>
                {amortizationSchedule.map((row) => (
                  <Typography.Text key={row.period_index}>
                    {`#${row.period_index}: ${formatRequestBillingMonth(row.period_month)} · ${Number(row.monthly_amount).toLocaleString('ru-RU')} ${detail.currency}`}
                  </Typography.Text>
                ))}
              </Space>
            </TgDetailRow>
          ) : null}
          <TgDetailRow label="Связанный расход">
            {linkedExpensePath && linkedExpenseText ? (
              <RequestDetailFieldValue variant={variant} to={linkedExpensePath} returnTo={returnTo}>
                {linkedExpenseText}
              </RequestDetailFieldValue>
            ) : linkedExpenseText ? (
              linkedExpenseText
            ) : (
              '—'
            )}
          </TgDetailRow>
          <TgDetailRow label="Дата оплаты">{formatPayedAt(detail.payed_at)}</TgDetailRow>
          <TgDetailRow label="Файлы">
            {fileRows.length ? (
              <Space direction="vertical" size={6} style={{ display: 'flex' }}>
                {fileRows.map((file) => (
                  <Button
                    key={file.key}
                    type="link"
                    onClick={() => void openFileViaAuthBlob(file.url)}
                    disabled={fileBusy}
                    loading={fileBusy}
                    style={{ padding: 0, justifyContent: 'flex-start' }}
                  >
                    {file.label}
                  </Button>
                ))}
              </Space>
            ) : (
              '—'
            )}
          </TgDetailRow>
        </div>
      ) : null}
      {detail && variant !== 'telegram' ? (
        <Descriptions bordered size="small" column={1}>
          <Descriptions.Item label="ID заявки">{detail.id}</Descriptions.Item>
          <Descriptions.Item label="Статус">
            <Tag color={getRequestStatusColor(detail.status)}>{detail.status}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Сумма">{`${Number(detail.amount).toLocaleString('ru-RU')} ${detail.currency}`}</Descriptions.Item>
          <Descriptions.Item label="Создано">{formatDateTime(detail.created_at)}</Descriptions.Item>
          <Descriptions.Item label="Кем создано">
            {createdByName && detail.created_by != null ? (
              <RequestEntityLink to={usersSettingsPath(detail.created_by)} returnTo={returnTo}>
                {createdByName}
              </RequestEntityLink>
            ) : (
              createdByName || '-'
            )}
          </Descriptions.Item>
          {detail.contract_ref_info ? (
            <Descriptions.Item label="Договор">
              {detail.contract_ref_info.contract_number || '-'}
              {formatContractPeriod(detail.contract_ref_info)
                ? ` · ${formatContractPeriod(detail.contract_ref_info)}`
                : ''}
            </Descriptions.Item>
          ) : null}
          <Descriptions.Item label="Заявитель">
            {requesterName && detail.requester != null ? (
              <RequestEntityLink to={usersSettingsPath(detail.requester)} returnTo={returnTo}>
                {requesterName}
              </RequestEntityLink>
            ) : (
              requesterName || '-'
            )}
          </Descriptions.Item>
          <Descriptions.Item label="Отправлено">{formatDateTime(detail.submitted_at)}</Descriptions.Item>
          <Descriptions.Item label="Дата биллинга">{formatRequestBillingMonth(detail.billing_date)}</Descriptions.Item>
          <Descriptions.Item label="Компания-плательщик">
            {detail.company_payer?.trim() ? (
              <RequestEntityLink to={REQUEST_FORM_CONFIG_PATH} returnTo={returnTo}>
                {detail.company_payer.trim()}
              </RequestEntityLink>
            ) : (
              '-'
            )}
          </Descriptions.Item>
          <Descriptions.Item label="Тип оплаты">
            {detail.payment_type ? (
              <RequestEntityLink to={REQUEST_FORM_CONFIG_PATH} returnTo={returnTo}>
                {detail.payment_type}
              </RequestEntityLink>
            ) : (
              '-'
            )}
          </Descriptions.Item>
          <Descriptions.Item label="Срочность">
            {detail.urgency ? (
              <RequestEntityLink to={REQUEST_FORM_CONFIG_PATH} returnTo={returnTo}>
                {detail.urgency}
              </RequestEntityLink>
            ) : (
              '-'
            )}
          </Descriptions.Item>
          <Descriptions.Item label="Категория">
            {detail.category ? (
              <RequestEntityLink to={REQUEST_FORM_CONFIG_PATH} returnTo={returnTo}>
                {detail.category}
              </RequestEntityLink>
            ) : (
              '-'
            )}
          </Descriptions.Item>
          <Descriptions.Item label="Поставщик">
            {vendorName && detail.vendor_ref != null ? (
              <RequestEntityLink to={contractsPath({ vendorId: detail.vendor_ref })} returnTo={returnTo}>
                {vendorName}
              </RequestEntityLink>
            ) : vendorName ? (
              <RequestEntityLink to={vendorDirectoryPath()} returnTo={returnTo}>
                {vendorName}
              </RequestEntityLink>
            ) : (
              '-'
            )}
          </Descriptions.Item>
          {detail.contract_ref != null ? (
            <Descriptions.Item label="Договор">
              <RequestEntityLink
                to={contractsPath({ contractId: detail.contract_ref, vendorId: detail.vendor_ref ?? undefined })}
                returnTo={returnTo}
              >
                {detail.contract_label?.trim() || `Договор #${detail.contract_ref}`}
              </RequestEntityLink>
            </Descriptions.Item>
          ) : null}
          <Descriptions.Item label="Назначение платежа">
            {detail.payment_purpose ? (
              <RequestEntityLink to={REQUEST_FORM_CONFIG_PATH} returnTo={returnTo}>
                {detail.payment_purpose}
              </RequestEntityLink>
            ) : (
              '-'
            )}
          </Descriptions.Item>
          <Descriptions.Item label="Описание">{detail.description || '-'}</Descriptions.Item>
          <Descriptions.Item label="Амортизация">
            {detail.is_amortized ? `Да (${detail.amortization_months || 0} мес.)` : 'Нет'}
          </Descriptions.Item>
          <Descriptions.Item label="Старт амортизации">
            {formatRequestBillingMonth(detail.amortization_start_date || null)}
          </Descriptions.Item>
          {amortizationSchedule.length ? (
            <Descriptions.Item label="График амортизации">
              <Space direction="vertical" size={4} style={{ display: 'flex' }}>
                {amortizationSchedule.map((row) => (
                  <Typography.Text key={row.period_index}>
                    {`#${row.period_index}: ${formatRequestBillingMonth(row.period_month)} · ${Number(row.monthly_amount).toLocaleString('ru-RU')} ${detail.currency}`}
                  </Typography.Text>
                ))}
              </Space>
            </Descriptions.Item>
          ) : null}
          <Descriptions.Item label="Связанный расход">
            {linkedExpensePath && linkedExpenseText ? (
              <RequestEntityLink to={linkedExpensePath} returnTo={returnTo}>
                {linkedExpenseText}
              </RequestEntityLink>
            ) : (
              linkedExpenseText || '-'
            )}
          </Descriptions.Item>
          <Descriptions.Item label="Дата оплаты">{formatPayedAt(detail.payed_at)}</Descriptions.Item>
          <Descriptions.Item label="Файлы">
            {fileRows.length ? (
              <Space direction="vertical" size={4} style={{ display: 'flex' }}>
                {fileRows.map((file) => (
                  <Button
                    key={file.key}
                    type="link"
                    onClick={() => void openFileViaAuthBlob(file.url)}
                    disabled={fileBusy}
                    loading={fileBusy}
                    style={{ paddingInline: 0, justifyContent: 'flex-start' }}
                  >
                    {file.label}
                  </Button>
                ))}
              </Space>
            ) : (
              '-'
            )}
          </Descriptions.Item>
        </Descriptions>
      ) : null}
      {loading ? <Skeleton active style={{ marginTop: 12 }} /> : null}
      {error ? <Alert type="error" showIcon message={error} style={{ marginTop: 12 }} /> : null}
      {!loading && detail ? (
        <>
          <Divider />
          <RequestCommentsSection
            requestId={detail.id}
            comments={detail.comments ?? []}
            onCommentAdded={onCommentAdded ?? (async () => {})}
            variant={variant}
          />
          <Divider />
          <Space direction="vertical" size={12} style={{ display: 'flex' }}>
            {renderApprovalGroup(`Одобрено (${approvedApprovals.length})`, approvedApprovals, {
              returnTo,
              variant,
            })}
            {renderApprovalGroup(`Отклонено (${rejectedApprovals.length})`, rejectedApprovals, {
              returnTo,
              variant,
            })}
            {renderApprovalGroup(`В ожидании (${pendingApprovals.length})`, pendingApprovals, {
              returnTo,
              variant,
            })}
          </Space>
        </>
      ) : null}
    </>
  )
}
