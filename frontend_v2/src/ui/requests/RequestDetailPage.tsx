import { useEffect, useState } from 'react'
import { Alert, Button, Card, DatePicker, Input, InputNumber, Modal, Select, Space, Typography, message } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import { apiFetch, confirmPaymentViaWebApp, resendRequestApprovals } from '../../lib/api'
import { getRequestFormOptions } from '../../lib/api'
import { RequestDetailContent, type ApprovalItem, type RequestDetail } from './RequestDetailModal'
import { NoteCreateModal } from '../NoteCreateModal'
import { useAuth } from '../auth'
import { clampToAllowedBillingMonth, isAllowedBillingMonth } from '../../lib/billingMonth'
import type { Dayjs } from 'dayjs'
import { monthStartTashkent } from '../../lib/tashkentTime'

export type RequestDetailPageProps = {
  /** Путь к списку заявок для кнопки «Назад» */
  listPath?: string
  /** Упрощённая вёрстка для Telegram Mini App */
  variant?: 'portal' | 'telegram'
}

function canOpenLinkedExpense(link: RequestDetail['expense_link'] | null | undefined): boolean {
  if (!link || link.id == null || link.id === '') return false
  return (
    link.module === 'cash' ||
    link.module === 'bank' ||
    link.module === 'payroll' ||
    link.module === 'corporate_card'
  )
}

function canResendByStatus(status?: string | null): boolean {
  const raw = String(status || '').trim()
  if (raw.toUpperCase() === 'APPROVED') return true
  const numeric = Number(raw)
  return Number.isFinite(numeric) && numeric >= 1 && numeric <= 5
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
  const { accessToken } = useAuth()
  const [detail, setDetail] = useState<RequestDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [openNoteModal, setOpenNoteModal] = useState(false)
  const [resendLoading, setResendLoading] = useState(false)
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
  const [uploadFile, setUploadFile] = useState<File | null>(null)
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
        setError('Request id is missing.')
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

  const openLinkedExpense = () => {
    const link = detail?.expense_link
    if (!canOpenLinkedExpense(link)) return
    const expId = String(link!.id)
    if (link!.module === 'cash') navigate(`/cash/${expId}`)
    if (link!.module === 'bank') navigate(`/bank/${expId}`)
    if (link!.module === 'payroll') navigate(`/payroll/${expId}`)
  }

  const resendRequest = async () => {
    if (!detail?.id) return
    setResendLoading(true)
    try {
      const { resent } = await resendRequestApprovals(detail.id)
      if (resent > 0) {
        message.success(`Заявки отправлены повторно: ${resent}`)
      } else {
        message.info('Нет pending-согласований для повторной отправки')
      }
      await refreshDetail()
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Не удалось отправить запрос повторно')
    } finally {
      setResendLoading(false)
    }
  }

  const link = detail?.expense_link
  const showExpenseButton = canOpenLinkedExpense(link)
  const showExternalExpenseHint = link?.module === 'external' && link.id != null && String(link.id) !== ''
  const resendAllowed = canResendByStatus(detail?.status)

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
      await confirmPaymentViaWebApp({ approval_id: approval.id, expense_id: expenseId })
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
    if (!detail?.id || !uploadFile) return
    setUploadBusy(true)
    try {
      const fd = new FormData()
      fd.append('file', uploadFile)
      const res = await apiFetch(`/api/requests/${detail.id}/file-upload/`, {
        method: 'POST',
        body: fd,
      })
      if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new Error(text || `HTTP ${res.status}`)
      }
      message.success('Файл прикреплён')
      setUploadOpen(false)
      setUploadFile(null)
      await refreshDetail()
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Не удалось загрузить файл')
    } finally {
      setUploadBusy(false)
    }
  }

  const approvalBtnSize = isTg ? ('large' as const) : undefined

  const pendingApprovalsEl =
    pendingApprovalsForMe.length > 0 ? (
      <div style={{ width: '100%', marginTop: isTg ? 4 : 12 }}>
        <Typography.Text strong style={{ display: 'block', marginBottom: 8 }}>
          На рассмотрении
        </Typography.Text>
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
                      Подтверждение выплаты выполняется через callback-интеграцию.
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
        <Space direction="vertical" size={12} style={{ display: 'flex' }}>
          {isTg ? (
            <div className="tg-actions-stack">
              <Button type="default" size="large" block onClick={() => navigate(listPath)}>
                ← К списку заявок
              </Button>
              {detail?.id ? (
                <Button size="large" block onClick={() => setOpenNoteModal(true)}>
                  Добавить заметку
                </Button>
              ) : null}
              {detail?.id ? (
                <Button
                  size="large"
                  block
                  icon={<ReloadOutlined />}
                  loading={resendLoading}
                  disabled={!resendAllowed}
                  title={
                    resendAllowed
                      ? 'Повторно отправить pending-согласования текущего этапа'
                      : 'Доступно для этапов согласования (1–5) и для заявок со статусом APPROVED'
                  }
                  onClick={() => void resendRequest()}
                >
                  Отправить запрос повторно
                </Button>
              ) : null}
              {detail?.id && !resendAllowed ? (
                <Typography.Text type="secondary" style={{ display: 'block', textAlign: 'center' }}>
                  Повторная отправка доступна на этапах согласования (1–5) и для заявок со статусом APPROVED.
                </Typography.Text>
              ) : null}
              {canEditDraft ? (
                <Button size="large" block onClick={() => setEditOpen(true)}>
                  Редактировать DRAFT
                </Button>
              ) : null}
              {canEditDraft ? (
                <Button size="large" block onClick={() => setUploadOpen(true)}>
                  Прикрепить файл
                </Button>
              ) : null}
              {pendingApprovalsEl}
              {showExpenseButton ? (
                <Button type="primary" size="large" block onClick={openLinkedExpense}>
                  Связанный расход
                </Button>
              ) : null}
              {showExternalExpenseHint ? (
                <Typography.Text type="secondary" style={{ display: 'block', textAlign: 'center' }}>
                  Расход не в кассе/банке приложения (внешний ID: {String(link?.id)}).
                </Typography.Text>
              ) : null}
            </div>
          ) : (
            <Space direction="vertical" size={12} style={{ display: 'flex', width: '100%' }}>
              <Space wrap align="start">
                <Button onClick={() => navigate(listPath)}>Назад к списку</Button>
                {canEditDraft ? (
                  <>
                    <Button onClick={() => setEditOpen(true)}>Редактировать черновик</Button>
                    <Button onClick={() => setUploadOpen(true)}>Прикрепить файл</Button>
                  </>
                ) : null}
                {detail?.id ? <Button onClick={() => setOpenNoteModal(true)}>Добавить заметку</Button> : null}
                {detail?.id ? (
                  <Button
                    icon={<ReloadOutlined />}
                    loading={resendLoading}
                    disabled={!resendAllowed}
                    title={
                      resendAllowed
                        ? 'Повторно отправить pending-согласования текущего этапа'
                        : 'Доступно для этапов согласования (1–5) и для заявок со статусом APPROVED'
                    }
                    onClick={() => void resendRequest()}
                  >
                    Отправить запрос повторно
                  </Button>
                ) : null}
                {showExpenseButton ? (
                  <Button type="primary" onClick={openLinkedExpense}>
                    Открыть связанный расход
                  </Button>
                ) : showExternalExpenseHint ? (
                  <Typography.Text type="secondary">Внешний расход (ID {String(link?.id)})</Typography.Text>
                ) : (
                  <Typography.Text type="secondary">Связанный расход не найден</Typography.Text>
                )}
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
            Укажите номер платежа (`expense_id`) для подтверждения payment-шага.
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
        title="Редактировать DRAFT"
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
        title="Прикрепить файл"
        onCancel={() => {
          setUploadOpen(false)
        }}
        footer={null}
        destroyOnClose
      >
        <Space direction="vertical" size={12} style={{ display: 'flex' }}>
          <input
            type="file"
            onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
            style={{ width: '100%' }}
          />

          <Typography.Text type="secondary" style={{ display: 'block' }}>
            {uploadFile ? `Выбрано: ${uploadFile.name}` : 'Файл не выбран'}
          </Typography.Text>

          <Button type="primary" block loading={uploadBusy} disabled={!uploadFile} onClick={() => void submitUpload()}>
            Загрузить
          </Button>
        </Space>
      </Modal>
    </Card>
  )
}
