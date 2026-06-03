import { useEffect, useState } from 'react'
import { Alert, Button, Card, DatePicker, Input, InputNumber, Modal, Select, Space, Typography, Upload, message } from 'antd'
import type { UploadFile } from 'antd/es/upload/interface'
import { CopyOutlined, PlusOutlined, ReloadOutlined, SendOutlined } from '@ant-design/icons'
import { useNavigate, useParams, useLocation } from 'react-router-dom'
import { RequestReturnBackButton } from './RequestReturnBackButton'
import {
  apiFetch,
  confirmPaymentViaWebApp,
  copyPortalRequest,
  getRequestFormOptions,
  deleteRequestAttachment,
  submitRequestForApproval,
  REQUEST_ATTACHMENT_MAX_FILES,
  uploadRequestAttachment,
  validateRequestAttachment,
} from '../../lib/api'
import { RequestDetailContent, type ApprovalItem, type RequestDetail } from './RequestDetailModal'
import { NoteCreateModal } from '../NoteCreateModal'
import { useAuth } from '../auth'
import { clampToAllowedBillingMonth, isAllowedBillingMonth } from '../../lib/billingMonth'
import { canOpenLinkedExpense, linkedExpenseFrontendPath, linkedExpenseLabel } from '../../lib/requestExpense'
import { readRequestReturnTo, requestReturnState, requestReturnToForDetail } from '../../lib/requestNavigation'
import type { Dayjs } from 'dayjs'
import { monthStartTashkent } from '../../lib/tashkentTime'

export type RequestDetailPageProps = {
  /** Путь к списку заявок для кнопки «Назад» */
  listPath?: string
  /** Упрощённая вёрстка для Telegram Mini App */
  variant?: 'portal' | 'telegram'
}


function isPaymentApprovalStep(a: ApprovalItem): boolean {
  return String(a.step_type || '').toLowerCase() === 'payment'
}

/** Smallest step number that still has pending approvals (matches backend workflow). */
function minPendingApprovalStep(approvals: ApprovalItem[] | undefined): number | null {
  if (!approvals?.length) return null
  const pendingSteps = approvals
    .filter((a) => String(a.decision || '').toLowerCase() === 'pending')
    .map((a) => a.step)
  if (!pendingSteps.length) return null
  return Math.min(...pendingSteps)
}

export function RequestDetailPage({ listPath = '/requests', variant = 'portal' }: RequestDetailPageProps) {
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const { state: locationState } = useLocation()
  const { accessToken } = useAuth()
  const [showCreatedAlert, setShowCreatedAlert] = useState(
    Boolean((locationState as Record<string, unknown> | null)?.justCreated),
  )
  const [detail, setDetail] = useState<RequestDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [openNoteModal, setOpenNoteModal] = useState(false)
  const [submitLoading, setSubmitLoading] = useState(false)
  const [approvalBusy, setApprovalBusy] = useState(false)
  const [isTenantAdmin, setIsTenantAdmin] = useState(false)

  const [editOpen, setEditOpen] = useState(false)
  const [editSaving, setEditSaving] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const [editDescription, setEditDescription] = useState('')
  const [editAmount, setEditAmount] = useState<number | null>(null)
  const [editCurrency, setEditCurrency] = useState('UZS')
  const [editUrgency, setEditUrgency] = useState('Обычно')
  const [editBillingDate, setEditBillingDate] = useState<Dayjs | null>(null)

  const [uploadOpen, setUploadOpen] = useState(false)
  const [uploadBusy, setUploadBusy] = useState(false)
  const [uploadFileList, setUploadFileList] = useState<UploadFile[]>([])
  const [paymentModalOpen, setPaymentModalOpen] = useState(false)
  const [paymentModalApproval, setPaymentModalApproval] = useState<ApprovalItem | null>(null)
  const [paymentExpenseId, setPaymentExpenseId] = useState('')

  const decodeJwtUserId = (token: string | null): number | null => {
    if (!token) return null
    try {
      const parts = token.split('.')
      if (parts.length < 2) return null
      const payload = parts[1]
      const base64 = payload.replace(/-/g, '+').replace(/_/g, '/')
      const padding = '='.repeat((4 - (base64.length % 4)) % 4)
      const json = decodeURIComponent(
        atob(base64 + padding)
          .split('')
          .map((c) => `%${c.charCodeAt(0).toString(16).padStart(2, '0')}`)
          .join(''),
      )
      const data = JSON.parse(json) as Record<string, unknown>
      const v = data.user_id ?? data.userId ?? data.sub
      if (typeof v === 'number') return v
      const n = typeof v === 'string' ? Number(v) : NaN
      if (!Number.isFinite(n)) return null
      return n
    } catch {
      return null
    }
  }

  const currentUserId = decodeJwtUserId(accessToken)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      if (!id) {
        setError('ID заявки не указан.')
        setLoading(false)
        return
      }
      setLoading(true)
      setError(null)
      try {
        const res = await apiFetch(`/api/requests/${id}/`)
        const json = (await res.json().catch(() => null)) as RequestDetail | null
        if (!res.ok) {
          throw new Error(typeof json === 'object' && json ? JSON.stringify(json) : `HTTP ${res.status}`)
        }
        if (!cancelled) setDetail(json)
      } catch (e: any) {
        if (!cancelled) setError(e?.message || 'Ошибка загрузки заявки')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [id])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const opts = await getRequestFormOptions()
        if (!cancelled) {
          setIsTenantAdmin(Boolean(opts.is_tenant_admin))
        }
      } catch {
        if (!cancelled) {
          setIsTenantAdmin(false)
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const refreshDetail = async () => {
    if (!id) return
    setLoading(true)
    setError(null)
    try {
      const res = await apiFetch(`/api/requests/${id}/`)
      const json = (await res.json().catch(() => null)) as RequestDetail | null
      if (!res.ok) {
        throw new Error(typeof json === 'object' && json ? JSON.stringify(json) : `HTTP ${res.status}`)
      }
      setDetail(json)
    } catch (e: any) {
      setError(e?.message || 'Ошибка загрузки заявки')
    } finally {
      setLoading(false)
    }
  }

  const activeApprovalStep = minPendingApprovalStep(detail?.approvals)
  const pendingApprovalsForMe =
    detail?.approvals?.filter(
      (a) =>
        String(a.decision || '').toLowerCase() === 'pending' &&
        a.approver_user === currentUserId &&
        activeApprovalStep != null &&
        a.step === activeApprovalStep,
    ) || []

  const isTg = variant === 'telegram'
  const canEditDraft =
    detail?.status === 'DRAFT' &&
    currentUserId != null &&
    (isTenantAdmin ||
      detail.requester === currentUserId ||
      (detail.created_by != null && detail.created_by === currentUserId))

  useEffect(() => {
    if (!editOpen || !detail) return
    setEditTitle(detail.title || '')
    setEditDescription(detail.description || '')
    setEditAmount(detail.amount ?? null)
    setEditCurrency(detail.currency || 'UZS')
    setEditUrgency(detail.urgency || 'Обычно')
    setEditBillingDate(detail.billing_date ? monthStartTashkent(detail.billing_date) : clampToAllowedBillingMonth(monthStartTashkent()))
  }, [editOpen, detail])

  const requestReturnTo =
    detail?.id != null
      ? requestReturnToForDetail(detail.id, { telegram: isTg })
      : undefined

  const openLinkedExpense = () => {
    const path = linkedExpenseFrontendPath(detail?.expense_link ?? null, { telegram: isTg })
    if (path && requestReturnTo) navigate(path, { state: requestReturnState(requestReturnTo) })
  }

  const submitDraft = async () => {
    if (!detail?.id) return
    setSubmitLoading(true)
    try {
      const { status: newStatus } = await submitRequestForApproval(detail.id)
      if (!newStatus || newStatus === 'DRAFT') {
        // Backend returns 200 but keeps DRAFT when no approval steps/approvers are configured
        // for this payment type, so nothing was actually routed.
        message.warning('Заявка осталась черновиком: для этого типа оплаты не настроены согласующие.')
      } else {
        message.success('Заявка отправлена на согласование')
      }
      await refreshDetail()
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Не удалось отправить заявку на согласование')
    } finally {
      setSubmitLoading(false)
    }
  }

  const duplicateRequest = async () => {
    if (!detail?.id) return
    try {
      const created = await copyPortalRequest(detail.id)
      message.success(`Черновик-копия создан: #${created.request_id}`)
      navigate(`${listPath}/${created.request_id}`)
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Не удалось скопировать заявку')
    }
  }

  const link = detail?.expense_link ?? null
  const showExpenseButton = canOpenLinkedExpense(link)
  const showExternalExpenseHint = link?.module === 'external' && link.id != null && String(link.id) !== ''
  const setDecision = async (step: number, decision: 'approved' | 'rejected') => {
    if (!detail?.id) return
    setApprovalBusy(true)
    try {
      const res = await apiFetch(`/api/requests/${detail.id}/approvals/decision/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ step, decision }),
      })
      if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new Error(text || `HTTP ${res.status}`)
      }
      message.success(decision === 'approved' ? 'Шаг одобрен' : 'Шаг отклонён')
      await refreshDetail()
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Не удалось обновить решение')
    } finally {
      setApprovalBusy(false)
    }
  }

  const openPaymentConfirmModal = (approval: ApprovalItem) => {
    setPaymentModalApproval(approval)
    setPaymentExpenseId((detail?.expense_id || '').trim())
    setPaymentModalOpen(true)
  }

  const closePaymentConfirmModal = () => {
    setPaymentModalOpen(false)
    setPaymentModalApproval(null)
    setPaymentExpenseId('')
  }

  const confirmPaymentStep = async () => {
    const approval = paymentModalApproval
    if (!approval) return
    const expenseId = paymentExpenseId.trim()
    if (!expenseId) {
      message.warning('Введите номер платежа')
      return
    }
    setApprovalBusy(true)
    try {
      await confirmPaymentViaWebApp({
        approval_id: approval.id,
        expense_id: expenseId,
      })
      message.success('Выплата подтверждена')
      closePaymentConfirmModal()
      await refreshDetail()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Ошибка подтверждения выплаты'
      message.error(msg)
      if (/callback/i.test(msg)) {
        message.info('Этот шаг настроен на подтверждение в Telegram — используйте бота.')
      }
    } finally {
      setApprovalBusy(false)
    }
  }

  const buildDraftPayload = () => ({
    title: editTitle.trim(),
    description: editDescription.trim(),
    amount: editAmount ?? 0,
    currency: editCurrency,
    urgency: editUrgency,
    billing_date: (editBillingDate ?? clampToAllowedBillingMonth(monthStartTashkent())).startOf('month').format('YYYY-MM-DD'),
  })

  const saveDraftOnly = async () => {
    if (!detail?.id) return
    if (!editTitle.trim()) {
      message.warning('Введите название заявки')
      return
    }
    if (!editBillingDate || !isAllowedBillingMonth(editBillingDate)) {
      message.warning('Выберите допустимый месяц биллинга')
      return
    }

    setEditSaving(true)
    try {
      const res = await apiFetch(`/api/requests/${detail.id}/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildDraftPayload()),
      })
      if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new Error(text || `HTTP ${res.status}`)
      }
      message.success('Черновик сохранён')
      setEditOpen(false)
      await refreshDetail()
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Не удалось сохранить черновик')
    } finally {
      setEditSaving(false)
    }
  }

  const submitDraftForApproval = async () => {
    if (!detail?.id) return
    if (!editTitle.trim()) {
      message.warning('Введите название заявки')
      return
    }
    if (editAmount == null || editAmount <= 0) {
      message.warning('Укажите сумму больше нуля для отправки на согласование')
      return
    }
    if (!editBillingDate || !isAllowedBillingMonth(editBillingDate)) {
      message.warning('Выберите допустимый месяц биллинга')
      return
    }

    setEditSaving(true)
    try {
      const res = await apiFetch(`/api/requests/${detail.id}/submit-for-approval/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildDraftPayload()),
      })
      if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new Error(text || `HTTP ${res.status}`)
      }
      message.success('Заявка отправлена на согласование')
      setEditOpen(false)
      await refreshDetail()
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Не удалось отправить на согласование')
    } finally {
      setEditSaving(false)
    }
  }

  const submitUpload = async () => {
    const uploadFiles = uploadFileList.map((f) => f.originFileObj as File).filter((f): f is File => f != null)
    if (!detail?.id || uploadFiles.length === 0) return
    const alreadyAttached = detail.attachments?.length ?? 0
    if (alreadyAttached + uploadFiles.length > REQUEST_ATTACHMENT_MAX_FILES) {
      message.warning(`Максимум ${REQUEST_ATTACHMENT_MAX_FILES} файлов на заявку`)
      return
    }
    for (const file of uploadFiles) {
      const err = validateRequestAttachment(file)
      if (err) {
        message.error(`${file.name}: ${err}`)
        return
      }
    }
    setUploadBusy(true)
    try {
      for (const file of uploadFiles) {
        await uploadRequestAttachment(detail.id, file)
      }
      message.success('Файлы прикреплены')
      setUploadOpen(false)
      setUploadFileList([])
      await refreshDetail()
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Не удалось загрузить файл')
    } finally {
      setUploadBusy(false)
    }
  }

  const removeAttachment = async (attachmentId: number) => {
    if (!detail?.id) return
    setUploadBusy(true)
    try {
      await deleteRequestAttachment(detail.id, attachmentId)
      message.success('Вложение удалено')
      await refreshDetail()
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Не удалось удалить вложение')
    } finally {
      setUploadBusy(false)
    }
  }

  const approvalBtnSize = isTg ? ('large' as const) : undefined

  const commentCount = detail?.comments?.length ?? 0

  const pendingApprovalsEl =
    pendingApprovalsForMe.length > 0 ? (
      <div style={{ width: '100%', marginTop: isTg ? 4 : 12 }}>
        <Typography.Text strong style={{ display: 'block', marginBottom: 8 }}>
          На рассмотрении
        </Typography.Text>
        {commentCount > 0 ? (
          <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 10, fontSize: 13 }}>
            <a
              href="#request-comments-section"
              onClick={(e) => {
                e.preventDefault()
                document.getElementById('request-comments-section')?.scrollIntoView({ behavior: 'smooth' })
              }}
            >
              💬 {commentCount} {commentCount === 1 ? 'комментарий' : commentCount < 5 ? 'комментария' : 'комментариев'} · перейти к обсуждению
            </a>
          </Typography.Text>
        ) : null}
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          {pendingApprovalsForMe.map((a) => (
            <div key={String(a.id)} style={{ width: '100%' }}>
              <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 6 }}>
                Шаг {a.step}
                {isPaymentApprovalStep(a) ? ' (выплата)' : ''}
              </Typography.Text>
              {isPaymentApprovalStep(a) ? (
                <Space direction="vertical" size={8} style={{ width: '100%' }}>
                  {String(a.payment_action_mode || '').toLowerCase() === 'webapp' ? (
                    <Button
                      type="primary"
                      size={approvalBtnSize}
                      block
                      loading={approvalBusy}
                      onClick={() => openPaymentConfirmModal(a)}
                    >
                      Подтвердить выплату
                    </Button>
                  ) : (
                    <Typography.Text type="secondary">
                      Подтверждение выплаты выполняется через Telegram-бота.
                    </Typography.Text>
                  )}
                  <Button
                    type="default"
                    size={approvalBtnSize}
                    block
                    loading={approvalBusy}
                    onClick={() => void setDecision(a.step, 'rejected')}
                  >
                    Отклонить
                  </Button>
                </Space>
              ) : (
                <Space direction="vertical" size={8} style={{ width: '100%' }}>
                  <Button
                    type="primary"
                    size={approvalBtnSize}
                    block
                    loading={approvalBusy}
                    onClick={() => void setDecision(a.step, 'approved')}
                  >
                    Одобрить
                  </Button>
                  <Button
                    type="default"
                    size={approvalBtnSize}
                    block
                    loading={approvalBusy}
                    onClick={() => void setDecision(a.step, 'rejected')}
                  >
                    Отклонить
                  </Button>
                </Space>
              )}
            </div>
          ))}
        </Space>
      </div>
    ) : null

  return (
    <Card className={isTg ? 'tg-detail-card' : undefined} styles={{ body: isTg ? { padding: '16px 16px 24px' } : undefined }}>
      <div className={isTg ? 'tg-detail-page' : undefined}>
        {showCreatedAlert ? (
          <Alert
            message="Заявка успешно создана!"
            description="Ваша заявка была создана и отправлена на согласование."
            type="success"
            showIcon
            closable
            onClose={() => setShowCreatedAlert(false)}
            style={{ marginBottom: 16, fontSize: 16 }}
          />
        ) : null}
        <Space direction="vertical" size={12} style={{ display: 'flex' }}>
          {isTg ? (
            <div className="tg-actions-stack">
              <Button
                type="default"
                size="large"
                block
                onClick={() => {
                  const returnTo = readRequestReturnTo(locationState)
                  navigate(returnTo?.pathname ?? listPath)
                }}
              >
                ← К списку заявок
              </Button>
              {detail?.id ? (
                <Button size="large" block onClick={() => setOpenNoteModal(true)}>
                  Добавить заметку
                </Button>
              ) : null}
              {canEditDraft ? (
                <Button
                  type="primary"
                  size="large"
                  block
                  icon={<SendOutlined />}
                  loading={submitLoading}
                  onClick={() => void submitDraft()}
                >
                  Отправить на согласование
                </Button>
              ) : null}
              {canEditDraft ? (
                <Button size="large" block onClick={() => setEditOpen(true)}>
                  Редактировать черновик
                </Button>
              ) : null}
              {canEditDraft ? (
                <Button size="large" block onClick={() => setUploadOpen(true)}>
                  Прикрепить файл
                </Button>
              ) : null}
              {detail?.id ? (
                <Button size="large" block icon={<CopyOutlined />} onClick={() => void duplicateRequest()}>
                  Копировать заявку
                </Button>
              ) : null}
              {pendingApprovalsEl}
              {showExpenseButton ? (
                <Button type="primary" size="large" block onClick={openLinkedExpense}>
                  {linkedExpenseLabel(link) || 'Связанный расход'}
                </Button>
              ) : null}
              {showExternalExpenseHint ? (
                <Typography.Text type="secondary" style={{ display: 'block', textAlign: 'center' }}>
                  {linkedExpenseLabel(link) || `Внешний платёж (ID ${String(link?.id)})`}
                </Typography.Text>
              ) : null}
            </div>
          ) : (
            <Space direction="vertical" size={12} style={{ display: 'flex', width: '100%' }}>
              <Space wrap align="start">
                <RequestReturnBackButton fallbackPath={listPath} fallbackLabel="Назад к списку" />
                {canEditDraft ? (
                  <>
                    <Button
                      type="primary"
                      icon={<SendOutlined />}
                      loading={submitLoading}
                      onClick={() => void submitDraft()}
                    >
                      Отправить на согласование
                    </Button>
                    <Button onClick={() => setEditOpen(true)}>Редактировать черновик</Button>
                    <Button onClick={() => setUploadOpen(true)}>Прикрепить файл</Button>
                  </>
                ) : null}
                {detail?.id ? <Button onClick={() => setOpenNoteModal(true)}>Добавить заметку</Button> : null}
                {detail?.id ? (
                  <Button icon={<CopyOutlined />} onClick={() => void duplicateRequest()}>
                    Копировать заявку
                  </Button>
                ) : null}
                {showExpenseButton ? (
                  <Button type="primary" onClick={openLinkedExpense}>
                    {linkedExpenseLabel(link) || 'Открыть связанный расход'}
                  </Button>
                ) : showExternalExpenseHint ? (
                  <Typography.Text type="secondary">
                    {linkedExpenseLabel(link) || `Внешний платёж (ID ${String(link?.id)})`}
                  </Typography.Text>
                ) : detail?.status === 'PAYED' ? (
                  <Typography.Text type="secondary">Связанный расход не найден</Typography.Text>
                ) : null}
              </Space>
              {pendingApprovalsEl}
            </Space>
          )}
          {error && !loading ? <Alert type="error" showIcon message={error} /> : null}
          <RequestDetailContent
            detail={detail}
            loading={loading}
            error={error}
            variant={isTg ? 'telegram' : 'default'}
            returnTo={requestReturnTo}
            onCommentAdded={refreshDetail}
            onRefresh={refreshDetail}
          />
        </Space>
      </div>
      <NoteCreateModal
        open={openNoteModal}
        onCancel={() => setOpenNoteModal(false)}
        targetType="request"
        targetId={detail?.id || null}
      />
      <Modal
        open={paymentModalOpen}
        title="Подтверждение выплаты"
        onCancel={closePaymentConfirmModal}
        footer={null}
        destroyOnClose
      >
        <Space direction="vertical" size={12} style={{ display: 'flex' }}>
          <Typography.Text type="secondary">
            Укажите номер платёжного документа для подтверждения шага выплаты.
          </Typography.Text>
          <Input
            value={paymentExpenseId}
            onChange={(e) => setPaymentExpenseId(e.target.value)}
            placeholder="Номер платежа"
            onPressEnter={() => void confirmPaymentStep()}
          />
          <Button type="primary" block loading={approvalBusy} onClick={() => void confirmPaymentStep()}>
            Подтвердить выплату
          </Button>
        </Space>
      </Modal>

      <Modal
        open={editOpen}
        title="Редактировать черновик"
        onCancel={() => {
          setEditOpen(false)
        }}
        footer={null}
        destroyOnClose
      >
        <Space direction="vertical" size={12} style={{ display: 'flex' }}>
          <div>
            <Typography.Text strong style={{ display: 'block', marginBottom: 6 }}>
              Название
            </Typography.Text>
            <Input value={editTitle} onChange={(e) => setEditTitle(e.target.value)} />
          </div>

          <div>
            <Typography.Text strong style={{ display: 'block', marginBottom: 6 }}>
              Описание
            </Typography.Text>
            <Input.TextArea rows={4} value={editDescription} onChange={(e) => setEditDescription(e.target.value)} />
          </div>

          <Space wrap size={12}>
            <div style={{ minWidth: 140 }}>
              <Typography.Text strong style={{ display: 'block', marginBottom: 6 }}>
                Сумма
              </Typography.Text>
              <InputNumber
                style={{ width: '100%' }}
                min={0}
                value={editAmount ?? undefined}
                onChange={(v) => setEditAmount(typeof v === 'number' ? v : null)}
              />
            </div>

            <div style={{ minWidth: 120 }}>
              <Typography.Text strong style={{ display: 'block', marginBottom: 6 }}>
                Валюта
              </Typography.Text>
              <Select
                style={{ width: '100%' }}
                value={editCurrency}
                onChange={(v) => setEditCurrency(v)}
                options={['UZS', 'USD', 'EUR', 'RUB'].map((c) => ({ value: c, label: c }))}
              />
            </div>

            <div style={{ minWidth: 160 }}>
              <Typography.Text strong style={{ display: 'block', marginBottom: 6 }}>
                Срочность
              </Typography.Text>
              <Select
                style={{ width: '100%' }}
                value={editUrgency}
                onChange={(v) => setEditUrgency(v)}
                options={[
                  { value: 'Низко', label: 'Низко' },
                  { value: 'Обычно', label: 'Обычно' },
                  { value: 'Срочно', label: 'Срочно' },
                ]}
              />
            </div>
          </Space>

          <div>
            <Typography.Text strong style={{ display: 'block', marginBottom: 6 }}>
              Месяц биллинга
            </Typography.Text>
            <DatePicker
              picker="month"
              format="MM.YYYY"
              style={{ display: 'block', width: '100%' }}
              value={editBillingDate}
              onChange={(v) => setEditBillingDate(v)}
              disabledDate={(current) => !current || !isAllowedBillingMonth(current)}
              inputReadOnly
            />
          </div>

          <Button loading={editSaving} disabled={loading} block onClick={() => void saveDraftOnly()}>
            Сохранить
          </Button>
          <Button type="primary" block loading={editSaving} disabled={loading} onClick={() => void submitDraftForApproval()}>
            Отправить на согласование
          </Button>
        </Space>
      </Modal>

      <Modal
        open={uploadOpen}
        title="Прикрепить файлы"
        onCancel={() => {
          setUploadOpen(false)
          setUploadFileList([])
        }}
        footer={null}
        destroyOnClose
      >
        <Space direction="vertical" size={12} style={{ display: 'flex' }}>
          <Upload
            multiple
            beforeUpload={() => false}
            fileList={uploadFileList}
            onChange={({ fileList }) => setUploadFileList(fileList)}
          >
            <Button icon={<PlusOutlined />}>Выбрать файлы</Button>
          </Upload>
          {detail?.attachments?.length ? (
            <>
              <Typography.Text type="secondary">Уже прикреплено:</Typography.Text>
              <Space direction="vertical" size={6} style={{ display: 'flex' }}>
                {detail.attachments.map((attachment) => (
                  <Space key={attachment.id} style={{ justifyContent: 'space-between', width: '100%' }}>
                    <Typography.Text>{attachment.name}</Typography.Text>
                    <Button danger size="small" loading={uploadBusy} onClick={() => void removeAttachment(attachment.id)}>
                      Удалить
                    </Button>
                  </Space>
                ))}
              </Space>
            </>
          ) : null}
          <Button type="primary" block loading={uploadBusy} disabled={uploadFileList.length === 0} onClick={() => void submitUpload()}>
            Загрузить
          </Button>
        </Space>
      </Modal>
    </Card>
  )
}
