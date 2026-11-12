import { useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Button, Typography, message, theme } from 'antd'
import {
  CopyOutlined,
  EditOutlined,
  ExclamationCircleOutlined,
  FileTextOutlined,
  MoreOutlined,
  PaperClipOutlined,
  ReloadOutlined,
  SendOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import { apiFetch } from '../../lib/api'
import { buildRequestFileRows, type RequestFileRow } from '../../lib/requestFiles'
import {
  isPayedMissingLinkedExpense,
  linkedExpenseFrontendPath,
  linkedExpenseLabel,
} from '../../lib/requestExpense'
import { requestReturnState, requestReturnToForDetail } from '../../lib/requestNavigation'
import { requestStatusColor, requestStatusLabel } from '../../lib/requestStatusLabels'
import { formatRequestBillingMonth } from '../../lib/requestUtils'
import { saveFile } from '../../lib/saveFile'
import { MobileSheet } from '../MobileSheet'
import { MobileStateWidget } from '../MobileStateWidget'
import { useMobileHeader } from '../mobileShell'
import { MobileActionsTheme, mobileToneTextColor } from './mobileActionsTheme'
import { PaymentConfirmSheet } from './PaymentConfirmSheet'
import { RejectRequestSheet } from './RejectRequestSheet'
import { RequestApprovalsTimelineWidget } from './RequestApprovalsTimelineWidget'
import { RequestCommentsSection } from './RequestCommentsSection'
import {
  ApprovalResendButton,
  formatContractPeriod,
  formatDateTime,
  formatPayedAt,
  translateStepType,
  type ApprovalItem,
  type RequestDetail,
} from './RequestDetailModal'
import { isNotificationApprovalStep, isPaymentApprovalStep } from './requestApprovalSteps'
import { RequestStatusToneTag, formatRequestAmount } from './RequestMobileCardWidget'
import { useMobileApprovalActions } from './useMobileApprovalActions'
import { useRequestInvestmentIds } from './useRequestInvestments'

export type RequestDetailMobileViewProps = {
  detail: RequestDetail | null
  loading: boolean
  error: string | null
  refreshDetail: () => Promise<void>
  /** Smallest step that still waits for a decision (the step the backend accepts decisions for). */
  activeApprovalStep: number | null
  /** The signed-in user's pending approvals of the active step (matched by `approver_user`). */
  pendingApprovalsForMe: ApprovalItem[]
  canEditDraft: boolean
  submitLoading: boolean
  onSubmitDraft: () => void
  onEditDraft: () => void
  onUploadFiles: () => void
  onOpenNote: () => void
  onDuplicate: () => void
}

const REQUESTS_PATH = '/requests'

/**
 * A request on a phone: hero with the human status, «Ждёт вашего решения» and a pinned «Отклонить / Одобрить» bar when
 * the user's step is active, fields as «label over value», files as rows, the approvals timeline and the comments.
 * The «⋯» menu of the header holds the draft actions, resending the approval card, a note and a copy.
 * Data and the draft/note/upload dialogs stay in RequestDetailPage; decisions go through useMobileApprovalActions.
 */
export function RequestDetailMobileView({
  detail,
  loading,
  error,
  refreshDetail,
  activeApprovalStep,
  pendingApprovalsForMe,
  canEditDraft,
  submitLoading,
  onSubmitDraft,
  onEditDraft,
  onUploadFiles,
  onOpenNote,
  onDuplicate,
}: RequestDetailMobileViewProps) {
  const { token } = theme.useToken()
  const [menuOpen, setMenuOpen] = useState(false)
  const [resendOpen, setResendOpen] = useState(false)
  const [rejectOpen, setRejectOpen] = useState(false)
  const [paymentOpen, setPaymentOpen] = useState(false)
  const actions = useMobileApprovalActions(detail?.id ?? null, refreshDetail)

  // A notification step needs no action from the user: no plaque and no buttons for it.
  const myActionable = pendingApprovalsForMe.filter((a) => !isNotificationApprovalStep(a))
  const myApproval = myActionable[0] ?? null
  const myNotificationOnly = pendingApprovalsForMe.length > 0 && myActionable.length === 0
  const isPayment = myApproval ? isPaymentApprovalStep(myApproval) : false
  const paymentViaWebApp = myApproval ? String(myApproval.payment_action_mode || '').toLowerCase() === 'webapp' : false

  // The backend's can_resend already checks the pending decision, the Telegram card and the resend limit; the request
  // status is not limited here, so the payment step of an APPROVED request can be resent too (as on the desktop).
  const resendable = useMemo(
    () => (detail?.approvals || []).filter((a) => String(a.decision || '').toLowerCase() === 'pending' && a.can_resend),
    [detail],
  )

  const headerAction = useMemo(
    () =>
      detail ? (
        <Button
          type="text"
          className="m-header__button"
          icon={<MoreOutlined />}
          aria-label="Действия с заявкой"
          aria-haspopup="dialog"
          onClick={() => setMenuOpen(true)}
        />
      ) : undefined,
    [detail],
  )
  useMobileHeader({ title: detail ? `Заявка #${detail.id}` : 'Заявка', back: REQUESTS_PATH, action: headerAction })

  if (!detail) {
    if (loading) return <MobileStateWidget state="loading" rows={2} />
    return (
      <MobileStateWidget
        state="error"
        title="Не удалось открыть заявку"
        description={error || undefined}
        onRetry={() => void refreshDetail()}
      />
    )
  }

  const totalSteps = detail.approvals?.length ? Math.max(...detail.approvals.map((a) => a.step)) : null
  const sheetSummary = {
    id: detail.id,
    title: detail.title,
    vendor: detail.vendor,
    amount: formatRequestAmount(detail.amount, detail.currency),
  }
  const showBar = myApproval !== null

  const runMenu = (action: () => void) => () => {
    setMenuOpen(false)
    action()
  }

  return (
    <div className="m-root" data-testid="request-detail-mobile" style={{ display: 'grid', gap: 12, minWidth: 0 }}>
      <section
        aria-label="Заявка"
        style={{ padding: 16, borderRadius: token.borderRadiusLG, background: token.colorBgContainer, minWidth: 0 }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, minWidth: 0 }}>
          <Typography.Text style={{ color: token.colorTextSecondary, flexShrink: 0 }}>Заявка #{detail.id}</Typography.Text>
          <div style={{ minWidth: 0, display: 'flex', justifyContent: 'flex-end' }}>
            <RequestStatusToneTag tone={requestStatusColor(detail.status)}>
              {requestStatusLabel(detail.status, { context: 'card', totalSteps })}
            </RequestStatusToneTag>
          </div>
        </div>
        <Typography.Title level={2} style={{ margin: '8px 0 4px', fontSize: 18, lineHeight: 1.35, overflowWrap: 'anywhere' }}>
          {detail.title?.trim() || detail.payment_purpose?.trim() || 'Без названия'}
        </Typography.Title>
        {detail.vendor?.trim() ? (
          <Typography.Text style={{ display: 'block', color: token.colorTextSecondary, overflowWrap: 'anywhere' }}>
            {detail.vendor}
          </Typography.Text>
        ) : null}
        <div style={{ marginTop: 8, fontSize: 22, fontWeight: 600, overflowWrap: 'anywhere' }}>
          {formatRequestAmount(detail.amount, detail.currency)}
        </div>
      </section>

      {myApproval ? (
        <div
          role="status"
          data-testid="awaiting-my-decision"
          style={{
            display: 'flex',
            gap: 10,
            alignItems: 'flex-start',
            padding: '12px 16px',
            borderRadius: token.borderRadiusLG,
            background: token.colorWarningBg,
            border: `1px solid ${token.colorWarningBorder}`,
          }}
        >
          <ExclamationCircleOutlined aria-hidden style={{ color: token.colorWarning, fontSize: 18, marginTop: 2 }} />
          <div style={{ display: 'grid', gap: 2, minWidth: 0 }}>
            <Typography.Text strong>Ждёт вашего решения</Typography.Text>
            <Typography.Text>
              {`Шаг ${myApproval.step}${isPayment ? ` · ${translateStepType(myApproval.step_type)}` : ''}`}
              {isPayment && !paymentViaWebApp ? '. Подтверждение выплаты выполняется через Telegram-бота.' : ''}
            </Typography.Text>
          </div>
        </div>
      ) : null}

      {myNotificationOnly ? (
        <Typography.Text data-testid="notification-step-note" style={{ color: token.colorTextSecondary, padding: '0 4px' }}>
          Ваш шаг — уведомление. Подтверждение происходит автоматически при отправке сообщения.
        </Typography.Text>
      ) : null}

      {error ? (
        <MobileStateWidget state="error" title="Не удалось обновить заявку" description={error} onRetry={() => void refreshDetail()} />
      ) : null}

      <Section title="Детали">
        <RequestFieldsList detail={detail} />
      </Section>

      <Section title="Файлы">
        <RequestFilesList detail={detail} />
      </Section>

      <Section title="Согласования">
        <RequestApprovalsTimelineWidget approvals={detail.approvals || []} activeApprovalStep={activeApprovalStep} />
        {activeApprovalStep != null && !myApproval && !myNotificationOnly ? (
          <Typography.Text style={{ display: 'block', color: token.colorTextSecondary }}>
            Сейчас на шаге {activeApprovalStep}.
          </Typography.Text>
        ) : null}
      </Section>

      <section aria-label="Комментарии" style={sectionStyle(token)}>
        {/* The shared desktop section: the phone theme makes its small buttons 44 px and its secondary text darker. */}
        <MobileActionsTheme>
          <RequestCommentsSection
            requestId={detail.id}
            comments={detail.comments ?? []}
            onCommentAdded={refreshDetail}
          />
        </MobileActionsTheme>
      </section>

      {showBar ? (
        <>
          {/* Room for the fixed bar, so it never covers the last block (home indicator included). */}
          <div aria-hidden className="m-bottom-bar-spacer" />
          <MobileActionsTheme>
            <div
              className="m-bottom-bar m-bottom-bar--fixed"
              data-testid="request-decision-bar"
              style={{ background: token.colorBgContainer, borderTop: `1px solid ${token.colorBorderSecondary}` }}
            >
              <Button style={{ flex: 1, height: 44 }} disabled={actions.busy} onClick={() => setRejectOpen(true)}>
                Отклонить
              </Button>
              {isPayment ? (
                paymentViaWebApp ? (
                  <Button type="primary" style={{ flex: 1, height: 44 }} loading={actions.busy} onClick={() => setPaymentOpen(true)}>
                    Подтвердить выплату
                  </Button>
                ) : null
              ) : (
                <Button
                  type="primary"
                  style={{ flex: 1, height: 44 }}
                  loading={actions.busy}
                  onClick={() => void actions.decide(myApproval.step, 'approved')}
                >
                  Одобрить
                </Button>
              )}
            </div>
          </MobileActionsTheme>
        </>
      ) : null}

      <MobileSheet open={menuOpen} onClose={() => setMenuOpen(false)} title="Действия с заявкой">
        <ul aria-label="Действия с заявкой" style={{ listStyle: 'none', margin: '0 -16px', padding: 0 }}>
          {canEditDraft ? (
            <>
              <MenuRow icon={<EditOutlined />} onClick={runMenu(onEditDraft)}>
                Редактировать черновик
              </MenuRow>
              <MenuRow icon={<SendOutlined />} disabled={submitLoading} busy={submitLoading} onClick={runMenu(onSubmitDraft)}>
                Отправить на согласование
              </MenuRow>
              <MenuRow icon={<UploadOutlined />} onClick={runMenu(onUploadFiles)}>
                Прикрепить файл
              </MenuRow>
            </>
          ) : null}
          {resendable.length > 0 ? (
            <MenuRow icon={<ReloadOutlined />} onClick={runMenu(() => setResendOpen(true))}>
              Переотправить согласование
            </MenuRow>
          ) : null}
          <MenuRow icon={<FileTextOutlined />} onClick={runMenu(onOpenNote)}>
            Добавить заметку
          </MenuRow>
          <MenuRow icon={<CopyOutlined />} onClick={runMenu(onDuplicate)}>
            Копировать заявку
          </MenuRow>
        </ul>
      </MobileSheet>

      <MobileSheet open={resendOpen} onClose={() => setResendOpen(false)} title="Переотправить согласование">
        <div style={{ display: 'grid', gap: 12 }}>
          <Typography.Text style={{ color: token.colorTextSecondary }}>
            Карточка заявки придёт согласующему в Telegram ещё раз.
          </Typography.Text>
          {resendable.map((item) => (
            <div
              key={item.id}
              data-testid={`resend-approval-${item.id}`}
              style={{ display: 'grid', gap: 8, padding: 12, borderRadius: token.borderRadiusLG, background: token.colorFillQuaternary }}
            >
              <Typography.Text style={{ overflowWrap: 'anywhere' }}>
                {`Шаг ${item.step} · ${item.approver_username || 'Согласующий не определён'}`}
              </Typography.Text>
              {/* The desktop button with its cooldown; the phone theme only makes its small size a 44 px target. */}
              <MobileActionsTheme>
                <ApprovalResendButton item={item} requestId={detail.id} onResent={() => void refreshDetail()} />
              </MobileActionsTheme>
            </div>
          ))}
        </div>
      </MobileSheet>

      <RejectRequestSheet
        open={rejectOpen}
        onClose={() => setRejectOpen(false)}
        step={myApproval?.step ?? null}
        summary={sheetSummary}
        busy={actions.busy}
        onReject={(comment) => (myApproval ? actions.decide(myApproval.step, 'rejected', comment) : Promise.resolve(false))}
      />

      <PaymentConfirmSheet
        open={paymentOpen}
        onClose={() => setPaymentOpen(false)}
        summary={sheetSummary}
        initialExpenseId={detail.expense_id}
        busy={actions.busy}
        onConfirm={(expenseId) => (myApproval ? actions.confirmPayment(myApproval.id, expenseId) : Promise.resolve(false))}
      />
    </div>
  )
}

function sectionStyle(token: ReturnType<typeof theme.useToken>['token']) {
  return { padding: 16, borderRadius: token.borderRadiusLG, background: token.colorBgContainer, minWidth: 0 }
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  const { token } = theme.useToken()
  return (
    <section aria-label={title} style={sectionStyle(token)}>
      <Typography.Title level={3} style={{ fontSize: 16, margin: '0 0 12px' }}>
        {title}
      </Typography.Title>
      {children}
    </section>
  )
}

function MenuRow({
  icon,
  disabled = false,
  busy = false,
  onClick,
  children,
}: {
  icon: ReactNode
  disabled?: boolean
  busy?: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <li>
      <button type="button" className="m-list-row" disabled={disabled} aria-busy={busy || undefined} onClick={onClick}>
        <span aria-hidden style={{ fontSize: 18, display: 'inline-flex' }}>
          {icon}
        </span>
        <span style={{ flex: 1, minWidth: 0 }}>{children}</span>
      </button>
    </li>
  )
}

type FieldRow = { label: string; value: ReactNode }

/** Fields of the request as «label over value»; optional fields without a value are left out. */
function RequestFieldsList({ detail }: { detail: RequestDetail }) {
  const { token } = theme.useToken()
  const investmentIds = useRequestInvestmentIds(detail)
  const returnTo = requestReturnToForDetail(detail.id, { telegram: false })
  const expensePath = linkedExpenseFrontendPath(detail.expense_link ?? null, { telegram: false })
  const expenseText = linkedExpenseLabel(detail.expense_link ?? null)
  const payedNoExpense = isPayedMissingLinkedExpense(detail)

  const requesterName =
    detail.requester_username?.trim() || (detail.requester != null ? `Пользователь #${detail.requester}` : null)
  const createdByName =
    detail.created_by_username?.trim() || (detail.created_by != null ? `Пользователь #${detail.created_by}` : null)
  const purpose = detail.payment_purpose?.trim() || ''
  const description = detail.description?.trim() || ''

  const contract = detail.contract_ref_info
    ? [detail.contract_ref_info.contract_number, formatContractPeriod(detail.contract_ref_info)].filter(Boolean).join(' · ')
    : detail.contract_ref != null
      ? detail.contract_label?.trim() || `Договор #${detail.contract_ref}`
      : ''

  const rows: Array<FieldRow | null> = [
    { label: 'Тип оплаты', value: detail.payment_type || '—' },
    { label: 'Срочность', value: detail.urgency || '—' },
    { label: 'Категория', value: detail.category || '—' },
    { label: 'Поставщик', value: detail.vendor?.trim() || '—' },
    contract ? { label: 'Договор', value: contract } : null,
    { label: 'Компания-плательщик', value: detail.company_payer?.trim() || '—' },
    { label: 'Назначение платежа', value: purpose || '—' },
    description && description !== purpose ? { label: 'Описание', value: <span style={{ whiteSpace: 'pre-wrap' }}>{description}</span> } : null,
    { label: 'Заявитель', value: requesterName || '—' },
    createdByName && createdByName !== requesterName ? { label: 'Кем создано', value: createdByName } : null,
    { label: 'Создано', value: formatDateTime(detail.created_at) },
    detail.submitted_at ? { label: 'Отправлено', value: formatDateTime(detail.submitted_at) } : null,
    { label: 'Месяц биллинга', value: formatRequestBillingMonth(detail.billing_date) },
    detail.is_amortized
      ? {
          label: 'Амортизация',
          value: `${detail.amortization_months || 0} мес. с ${formatRequestBillingMonth(detail.amortization_start_date || null)}`,
        }
      : null,
    expensePath && expenseText
      ? {
          label: 'Связанный расход',
          value: (
            <Link to={expensePath} state={requestReturnState(returnTo)} style={{ color: token.colorPrimaryActive }}>
              {expenseText}
            </Link>
          ),
        }
      : expenseText
        ? { label: 'Связанный расход', value: expenseText }
        : payedNoExpense
          ? {
              label: 'Связанный расход',
              value: (
                <span data-testid="payed-no-expense-note" style={{ color: mobileToneTextColor('error', token) }}>
                  Оплачена, но расход не найден
                </span>
              ),
            }
          : null,
    investmentIds.length
      ? {
          label: 'Вложение',
          value: (
            <span style={{ display: 'grid', gap: 4 }}>
              {investmentIds.map((id) => (
                <Link key={id} to="/investments" state={requestReturnState(returnTo)} style={{ color: token.colorPrimaryActive }}>
                  {`Вошла во вложение №${id}`}
                </Link>
              ))}
            </span>
          ),
        }
      : null,
    detail.payed_at != null ? { label: 'Дата оплаты', value: formatPayedAt(detail.payed_at) } : null,
  ]

  // Links take the darker primary shade: #1677ff on white is about 4.1:1.
  return (
    <dl data-testid="request-fields" style={{ margin: 0, display: 'grid', gap: 12 }}>
      {rows
        .filter((row): row is FieldRow => row !== null)
        .map((row) => (
          <div key={row.label} style={{ display: 'grid', gap: 2, minWidth: 0 }}>
            {/* colorTextSecondary, not tertiary: 13 px labels need 4.5:1. */}
            <dt style={{ fontSize: 13, color: token.colorTextSecondary }}>{row.label}</dt>
            <dd style={{ margin: 0, overflowWrap: 'anywhere' }}>{row.value}</dd>
          </div>
        ))}
    </dl>
  )
}

/**
 * Files as touch rows. Same rule as the desktop card (lib/requestFiles.ts): a file URL is fetched with apiFetch (token
 * and company header) and saved through a hidden link, never opened as an href.
 */
function RequestFilesList({ detail }: { detail: RequestDetail }) {
  const { token } = theme.useToken()
  const [busyKey, setBusyKey] = useState<string | null>(null)
  const files = buildRequestFileRows(detail)

  if (!files.length) {
    return <Typography.Text style={{ color: token.colorTextSecondary }}>Файлов нет</Typography.Text>
  }

  const download = async (file: RequestFileRow) => {
    setBusyKey(file.key)
    try {
      const res = await apiFetch(file.url)
      if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new Error(text || `HTTP ${res.status}`)
      }
      const filename = file.label.replace(/\s\([^)]*\)$/, '').trim() || 'file'
      saveFile({ blob: await res.blob(), filename })
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Не удалось скачать файл')
    } finally {
      setBusyKey(null)
    }
  }

  return (
    <ul aria-label="Файлы" style={{ listStyle: 'none', margin: '0 -16px', padding: 0 }}>
      {files.map((file) => (
        <li key={file.key}>
          <button
            type="button"
            className="m-list-row"
            disabled={busyKey !== null}
            aria-busy={busyKey === file.key}
            onClick={() => void download(file)}
          >
            <PaperClipOutlined aria-hidden style={{ color: token.colorTextSecondary }} />
            <span className="m-ellipsis" style={{ flex: 1, color: token.colorPrimaryActive }}>
              {file.label}
            </span>
          </button>
        </li>
      ))}
    </ul>
  )
}
