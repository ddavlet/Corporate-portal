import { useState } from 'react'
import type { ReactNode } from 'react'
import { Alert, Button, Card, Descriptions, Divider, Modal, Skeleton, Space, Tag, Typography, message } from 'antd'
import { apiFetch } from '../../lib/api'
import type { RequestAttachment } from '../../lib/api'

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
  company_payer?: string
  payment_purpose?: string
  file_link?: string | null
  attachments?: RequestAttachment[]
  requester: number | null
  requester_username?: string | null
  created_at?: string
  created_by?: number | null
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
}

const dateFormatterTashkent = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  timeZone: 'Asia/Tashkent',
})
const billingMonthFormatterTashkent = new Intl.DateTimeFormat('ru-RU', {
  month: 'long',
  year: 'numeric',
  timeZone: 'Asia/Tashkent',
})

const dateTimeFormatterTashkent = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  timeZone: 'Asia/Tashkent',
})

function formatDateDDMMYYYY(value?: string | null): string {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '-'
  return dateFormatterTashkent.format(parsed)
}

function formatBillingMonthYear(value?: string | null): string {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '-'
  return billingMonthFormatterTashkent.format(parsed)
}

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

function formatExpenseCalendar(
  y?: number | null,
  m?: number | null,
  d?: number | null,
): string {
  if (y == null && m == null && d == null) return '-'
  return [y ?? '—', m != null ? String(m).padStart(2, '0') : '—', d != null ? String(d).padStart(2, '0') : '—'].join(
    '.',
  )
}

function expenseLinkSummary(link: RequestDetail['expense_link']): string {
  if (!link) return '-'
  const parts: string[] = []
  if (link.module) parts.push(`модуль: ${link.module}`)
  if (link.expense_type) parts.push(`тип: ${link.expense_type}`)
  if (link.doc_id != null && String(link.doc_id).trim() !== '') parts.push(`doc_id: ${link.doc_id}`)
  if (link.id != null && link.id !== '') parts.push(`связанный id: ${link.id}`)
  return parts.length ? parts.join(' · ') : '-'
}

function formatAttachmentSize(sizeBytes?: number): string {
  const size = Number(sizeBytes || 0)
  if (!Number.isFinite(size) || size <= 0) return '-'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

function getStatusColor(value: string): string | undefined {
  const normalized = String(value || '').trim().toUpperCase()
  if (normalized === 'REJECTED') return 'error'
  if (normalized === 'APPROVED') return 'success'
  if (normalized === 'PAYED') return '#8c8c8c'
  if (normalized === '1-5') return 'warning'
  const numericStatus = Number(normalized)
  if (Number.isFinite(numericStatus) && numericStatus >= 1 && numericStatus <= 5) return 'warning'
  return undefined
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

function renderApprovalGroup(title: string, items: ApprovalItem[]) {
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
                <Typography.Text>{`S${item.step}/${item.step_type}`}</Typography.Text>
                <Typography.Text>{item.approver_username || 'Unknown approver'}</Typography.Text>
                {item.approver_user != null ? (
                  <Typography.Text type="secondary">user #{item.approver_user}</Typography.Text>
                ) : null}
                <Tag color={getDecisionColor(item.decision)}>{String(item.decision || '').toUpperCase()}</Tag>
              </Space>
              <Typography.Text type="secondary">{item.comment || 'without comment'}</Typography.Text>
              <Typography.Text type="secondary">Решение: {formatDateDDMMYYYY(item.decided_at)}</Typography.Text>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                approval id: {item.id}
                {item.message_id != null ? ` · message_id: ${item.message_id}` : ''}
                {item.message_sent != null ? ` · message_sent: ${item.message_sent ? 'да' : 'нет'}` : ''}
                {item.message_sent_at ? ` · message_sent_at: ${formatDateTime(item.message_sent_at)}` : ''}
                {item.approver_tg_id != null && item.approver_tg_id !== ''
                  ? ` · tg_id: ${item.approver_tg_id}`
                  : ''}
                {item.approver_tg_from_id != null && item.approver_tg_from_id !== ''
                  ? ` · tg_from: ${item.approver_tg_from_id}`
                  : ''}
              </Typography.Text>
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
}

export function RequestDetailModal({
  open,
  onCancel,
  detail,
  loading = false,
  error = null,
  actions = null,
}: RequestDetailModalProps) {
  return (
    <Modal open={open} title={detail ? `Заявка #${detail.id}` : 'Заявка'} footer={null} onCancel={onCancel} width={760}>
      <RequestDetailContent detail={detail} loading={loading} error={error} actions={actions} />
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
}: RequestDetailContentProps) {
  const approvals = detail?.approvals || []
  const amortizationSchedule = detail?.amortization_schedule || []
  const approvedApprovals = approvals.filter((a) => decisionKey(a.decision) === 'approved')
  const rejectedApprovals = approvals.filter((a) => decisionKey(a.decision) === 'rejected')
  const pendingApprovals = approvals.filter((a) => decisionKey(a.decision) === 'pending')

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
      {actions ? <Space style={{ marginBottom: 12 }}>{actions}</Space> : null}
      {detail && variant === 'telegram' ? (
        <div>
          <div className="tg-detail-hero">
            <Typography.Title level={4} style={{ margin: 0, fontSize: 18, lineHeight: 1.35 }}>
              {detail.title || `Заявка #${detail.id}`}
            </Typography.Title>
            <div style={{ marginTop: 8 }}>
              <Tag color={getStatusColor(detail.status)}>{detail.status}</Tag>
            </div>
            <div className="tg-detail-amount">
              {`${Number(detail.amount).toLocaleString('ru-RU')} ${detail.currency}`}
            </div>
          </div>
          <TgDetailRow label="ID заявки">{detail.id}</TgDetailRow>
          <TgDetailRow label="Создано">{formatDateTime(detail.created_at)}</TgDetailRow>
          <TgDetailRow label="Кем создано">
            {detail.created_by != null && detail.created_by !== undefined ? `User #${detail.created_by}` : '—'}
          </TgDetailRow>
          <TgDetailRow label="Компания-плательщик">{detail.company_payer?.trim() || '—'}</TgDetailRow>
          <TgDetailRow label="Тип оплаты">{detail.payment_type || '—'}</TgDetailRow>
          <TgDetailRow label="Срочность">{detail.urgency || '—'}</TgDetailRow>
          <TgDetailRow label="Категория">{detail.category || '—'}</TgDetailRow>
          <TgDetailRow label="Поставщик">{detail.vendor || '—'}</TgDetailRow>
          <TgDetailRow label="ID поставщика (справочник)">
            {detail.vendor_ref != null && detail.vendor_ref !== undefined ? String(detail.vendor_ref) : '—'}
          </TgDetailRow>
          <TgDetailRow label="Назначение платежа">{detail.payment_purpose || '—'}</TgDetailRow>
          <TgDetailRow label="Описание">{detail.description || '—'}</TgDetailRow>
          <TgDetailRow label="Заявитель">
            {detail.requester_username || (detail.requester ? `User #${detail.requester}` : '—')}
          </TgDetailRow>
          <TgDetailRow label="Отправлено">{formatDateTime(detail.submitted_at)}</TgDetailRow>
          <TgDetailRow label="Дата биллинга">{formatBillingMonthYear(detail.billing_date)}</TgDetailRow>
          <TgDetailRow label="Амортизация">{detail.is_amortized ? `Да (${detail.amortization_months || 0} мес.)` : 'Нет'}</TgDetailRow>
          <TgDetailRow label="Старт амортизации">{formatBillingMonthYear(detail.amortization_start_date || null)}</TgDetailRow>
          {amortizationSchedule.length ? (
            <TgDetailRow label="График амортизации">
              <Space direction="vertical" size={4} style={{ display: 'flex' }}>
                {amortizationSchedule.map((row) => (
                  <Typography.Text key={row.period_index}>
                    {`#${row.period_index}: ${formatBillingMonthYear(row.period_month)} · ${Number(row.monthly_amount).toLocaleString('ru-RU')} ${detail.currency}`}
                  </Typography.Text>
                ))}
              </Space>
            </TgDetailRow>
          ) : null}
          <TgDetailRow label="ID расхода (expense_id)">{detail.expense_id?.trim() || '—'}</TgDetailRow>
          <TgDetailRow label="Календарь расхода (год.мес.день)">
            {formatExpenseCalendar(detail.expense_year, detail.expense_month, detail.expense_day)}
          </TgDetailRow>
          <TgDetailRow label="Связь с расходом">{expenseLinkSummary(detail.expense_link)}</TgDetailRow>
          <TgDetailRow label="Дата оплаты (payed_at)">{formatPayedAt(detail.payed_at)}</TgDetailRow>
          <TgDetailRow label="Файл">
            {detail.file_link ? (
              <Button type="link" onClick={() => void openFileViaAuthBlob(detail.file_link!)} disabled={fileBusy} loading={fileBusy}>
                Открыть файл
              </Button>
            ) : (
              '—'
            )}
          </TgDetailRow>
          <TgDetailRow label="Вложения">
            {detail.attachments?.length ? (
              <Space direction="vertical" size={6} style={{ display: 'flex' }}>
                {detail.attachments.map((attachment) => (
                  <Button
                    key={attachment.id}
                    type="link"
                    onClick={() => attachment.url && void openFileViaAuthBlob(attachment.url)}
                    disabled={fileBusy || !attachment.url}
                    style={{ padding: 0, justifyContent: 'flex-start' }}
                  >
                    {`${attachment.name} (${formatAttachmentSize(attachment.size_bytes)})`}
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
          <Descriptions.Item label="Создано">{formatDateTime(detail.created_at)}</Descriptions.Item>
          <Descriptions.Item label="Кем создано (user id)">
            {detail.created_by != null && detail.created_by !== undefined ? detail.created_by : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="Название">{detail.title || '-'}</Descriptions.Item>
          <Descriptions.Item label="Статус">
            <Tag color={getStatusColor(detail.status)}>{detail.status}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Компания-плательщик">{detail.company_payer?.trim() || '-'}</Descriptions.Item>
          <Descriptions.Item label="Сумма">{`${Number(detail.amount).toLocaleString('ru-RU')} ${detail.currency}`}</Descriptions.Item>
          <Descriptions.Item label="Тип оплаты">{detail.payment_type || '-'}</Descriptions.Item>
          <Descriptions.Item label="Срочность">{detail.urgency || '-'}</Descriptions.Item>
          <Descriptions.Item label="Категория">{detail.category || '-'}</Descriptions.Item>
          <Descriptions.Item label="Поставщик">{detail.vendor || '-'}</Descriptions.Item>
          <Descriptions.Item label="ID поставщика (справочник)">
            {detail.vendor_ref != null && detail.vendor_ref !== undefined ? detail.vendor_ref : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="Назначение платежа">{detail.payment_purpose || '-'}</Descriptions.Item>
          <Descriptions.Item label="Описание">{detail.description || '-'}</Descriptions.Item>
          <Descriptions.Item label="Заявитель">
            {detail.requester_username || (detail.requester ? `User #${detail.requester}` : '-')}
          </Descriptions.Item>
          <Descriptions.Item label="Отправлено">{formatDateTime(detail.submitted_at)}</Descriptions.Item>
          <Descriptions.Item label="Дата биллинга">{formatBillingMonthYear(detail.billing_date)}</Descriptions.Item>
          <Descriptions.Item label="Амортизация">
            {detail.is_amortized ? `Да (${detail.amortization_months || 0} мес.)` : 'Нет'}
          </Descriptions.Item>
          <Descriptions.Item label="Старт амортизации">
            {formatBillingMonthYear(detail.amortization_start_date || null)}
          </Descriptions.Item>
          {amortizationSchedule.length ? (
            <Descriptions.Item label="График амортизации">
              <Space direction="vertical" size={4} style={{ display: 'flex' }}>
                {amortizationSchedule.map((row) => (
                  <Typography.Text key={row.period_index}>
                    {`#${row.period_index}: ${formatBillingMonthYear(row.period_month)} · ${Number(row.monthly_amount).toLocaleString('ru-RU')} ${detail.currency}`}
                  </Typography.Text>
                ))}
              </Space>
            </Descriptions.Item>
          ) : null}
          <Descriptions.Item label="ID расхода (expense_id)">{detail.expense_id?.trim() || '-'}</Descriptions.Item>
          <Descriptions.Item label="Календарь расхода (год · мес · день)">
            {formatExpenseCalendar(detail.expense_year, detail.expense_month, detail.expense_day)}
          </Descriptions.Item>
          <Descriptions.Item label="Связь с расходом">
            <Space direction="vertical" size={4}>
              <Typography.Text>{expenseLinkSummary(detail.expense_link)}</Typography.Text>
              {detail.expense_link?.url ? (
                <Typography.Link href={detail.expense_link.url} target="_blank" rel="noopener noreferrer">
                  Ссылка API
                </Typography.Link>
              ) : null}
            </Space>
          </Descriptions.Item>
          <Descriptions.Item label="Дата оплаты (payed_at)">{formatPayedAt(detail.payed_at)}</Descriptions.Item>
          <Descriptions.Item label="Файл">
            {detail.file_link ? (
              <Button type="link" onClick={() => void openFileViaAuthBlob(detail.file_link!)} disabled={fileBusy} loading={fileBusy}>
                Открыть файл
              </Button>
            ) : (
              '-'
            )}
          </Descriptions.Item>
          <Descriptions.Item label="Вложения">
            {detail.attachments?.length ? (
              <Space direction="vertical" size={4} style={{ display: 'flex' }}>
                {detail.attachments.map((attachment) => (
                  <Button
                    key={attachment.id}
                    type="link"
                    onClick={() => attachment.url && void openFileViaAuthBlob(attachment.url)}
                    disabled={fileBusy || !attachment.url}
                    style={{ paddingInline: 0, justifyContent: 'flex-start' }}
                  >
                    {`${attachment.name} (${formatAttachmentSize(attachment.size_bytes)})`}
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
          <Space direction="vertical" size={12} style={{ display: 'flex' }}>
            {renderApprovalGroup(`Одобрено (${approvedApprovals.length})`, approvedApprovals)}
            {renderApprovalGroup(`Отклонено (${rejectedApprovals.length})`, rejectedApprovals)}
            {renderApprovalGroup(`В ожидании (${pendingApprovals.length})`, pendingApprovals)}
          </Space>
        </>
      ) : null}
    </>
  )
}
