import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Descriptions, Input, Modal, Skeleton, Space, Table, Tag, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { RequestReturnBackButton } from './requests/RequestReturnBackButton'
import { PayrollDocumentFormModal } from './payroll/PayrollDocumentFormModal'
import { PayrollPayoutModal } from './payroll/PayrollPayoutModal'
import { PAYROLL_STATUS_COLORS } from './payroll/payrollStatus'
import {
  PAYROLL_KIND_LABELS,
  PAYROLL_STATUS_LABELS,
  acceptPayrollDocument,
  cancelPayrollDocument,
  closePayrollDocumentUnderpaid,
  copyPayrollDocument,
  getPayrollDocument,
  getPayrollPayoutState,
  type PayrollDocumentDetailDto,
  type PayrollDocumentLineDto,
  type PayrollPayoutStateDto,
} from '../lib/api'

const dateFmt = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  timeZone: 'Asia/Tashkent',
})

function formatDate(value?: string | null): string {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '-'
  return dateFmt.format(parsed)
}

function formatPeriodMonth(value: string | null): string {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '-'
  const month = String(parsed.getUTCMonth() + 1).padStart(2, '0')
  const year = parsed.getUTCFullYear()
  return `${month}.${year}`
}

function fmtMoney(value: string | number): string {
  return Number(value).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function PayrollDocumentDetailPage() {
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const [detail, setDetail] = useState<PayrollDocumentDetailDto | null>(null)
  const [state, setState] = useState<PayrollPayoutStateDto | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [editOpen, setEditOpen] = useState(false)
  const [payoutOpen, setPayoutOpen] = useState(false)
  const [underpaidOpen, setUnderpaidOpen] = useState(false)
  const [underpaidComment, setUnderpaidComment] = useState('')
  const [underpaidSaving, setUnderpaidSaving] = useState(false)

  const reload = useCallback(async () => {
    if (!id) {
      setError('Не указан id документа.')
      setLoading(false)
      return
    }
    setLoading(true)
    setError(null)
    try {
      const doc = await getPayrollDocument(id)
      setDetail(doc)
      if (doc.payout_mode === 'portal' && doc.status !== 'draft') {
        try {
          const s = await getPayrollPayoutState(doc.id)
          setState(s)
        } catch (e: unknown) {
          // Состояние выплат — вспомогательные данные: страница должна открыться даже если оно не загрузилось.
          console.error('Не удалось загрузить состояние выплат начисления', e)
          setState(null)
        }
      } else {
        setState(null)
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    void reload()
  }, [reload])

  const handleAccept = () => {
    if (!detail) return
    Modal.confirm({
      title: 'Принять начисление?',
      content: `Будет создана заявка на ${fmtMoney(detail.total_sum)}.`,
      okText: 'Принять',
      cancelText: 'Отмена',
      onOk: async () => {
        try {
          await acceptPayrollDocument(detail.id)
          message.success('Начисление принято')
          await reload()
        } catch (e: unknown) {
          message.error(e instanceof Error ? e.message : 'Ошибка')
        }
      },
    })
  }

  const handleCancel = () => {
    if (!detail) return
    Modal.confirm({
      title: 'Отменить начисление?',
      okText: 'Отменить',
      okButtonProps: { danger: true },
      cancelText: 'Не отменять',
      onOk: async () => {
        try {
          await cancelPayrollDocument(detail.id)
          message.success('Начисление отменено')
          await reload()
        } catch (e: unknown) {
          message.error(e instanceof Error ? e.message : 'Ошибка')
        }
      },
    })
  }

  const handleCopy = async () => {
    if (!detail) return
    try {
      const copy = await copyPayrollDocument(detail.id)
      message.success('Начисление скопировано')
      navigate(`/payroll/${copy.id}`)
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Ошибка')
    }
  }

  const handleCloseUnderpaid = async () => {
    if (!detail || !underpaidComment.trim()) return
    setUnderpaidSaving(true)
    try {
      await closePayrollDocumentUnderpaid(detail.id, underpaidComment.trim())
      message.success('Начисление закрыто с недоплатой')
      setUnderpaidOpen(false)
      setUnderpaidComment('')
      await reload()
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Ошибка')
    } finally {
      setUnderpaidSaving(false)
    }
  }

  const lineColumns: ColumnsType<PayrollDocumentLineDto> = [
    { title: '№', dataIndex: 'line_no', width: 56 },
    { title: 'Сотрудник', dataIndex: 'employee' },
    { title: 'Вид', dataIndex: 'item', width: 140 },
    { title: 'Сумма', dataIndex: 'sum', width: 130, render: (v) => fmtMoney(v) },
    { title: 'Дни план', dataIndex: 'days_plan', width: 88 },
    { title: 'Дни факт', dataIndex: 'days_fact', width: 88 },
    {
      title: 'Период',
      key: 'period',
      width: 200,
      render: (_, r) => `${formatDate(r.period_start)} — ${formatDate(r.period_end)}`,
    },
    {
      title: 'Подтверждено',
      dataIndex: 'approval',
      width: 120,
      render: (v: boolean) => (v ? 'Да' : 'Нет'),
    },
  ]

  const employeeColumns: ColumnsType<NonNullable<PayrollPayoutStateDto['employees']>[number]> = [
    { title: 'Сотрудник', dataIndex: 'full_name' },
    { title: 'Начислено', dataIndex: 'accrued', width: 140, render: (v: string) => fmtMoney(v) },
    { title: 'Выплачено', dataIndex: 'paid', width: 140, render: (v: string) => fmtMoney(v) },
    { title: 'Остаток', dataIndex: 'remaining', width: 140, render: (v: string) => fmtMoney(v) },
  ]

  const expenseColumns: ColumnsType<NonNullable<PayrollPayoutStateDto['expenses']>[number]> = [
    { title: 'Дата', dataIndex: 'date', width: 140, render: (v: string) => formatDate(v) },
    { title: 'Сумма', dataIndex: 'amount', width: 140, render: (v: string) => fmtMoney(v) },
    {
      key: 'open',
      width: 120,
      render: (_, r) => (
        <Link to={`/cash/expenses/${r.cash_expense_id}`}>Открыть</Link>
      ),
    },
  ]

  const canEdit = detail?.status === 'draft' && detail?.source === 'portal'
  const canAccept = detail?.status === 'draft'
  const canCancel = detail?.status === 'draft'
  const canPay = Boolean(state?.can_pay)
  const canCloseUnderpaid =
    detail?.payout_mode === 'portal' && detail?.status === 'accepted' && detail?.current_request?.status === 'APPROVED'
  const showPayoutReasonAlert =
    Boolean(state) && !state?.can_pay && detail?.status === 'accepted' && detail?.payout_mode === 'portal'

  return (
    <Card>
      <Space direction="vertical" size={12} style={{ display: 'flex' }}>
        <RequestReturnBackButton fallbackPath="/payroll" fallbackLabel="Назад к списку" />
        {loading ? <Skeleton active /> : null}
        {error ? <Alert type="error" showIcon message={error} /> : null}
        {!loading && !error && detail ? (
          <>
            <Space align="center" wrap>
              <Typography.Title level={4} style={{ marginTop: 0, marginBottom: 0 }}>
                Начисление ЗП {detail.label}
              </Typography.Title>
              <Tag color={PAYROLL_STATUS_COLORS[detail.status]}>{PAYROLL_STATUS_LABELS[detail.status]}</Tag>
            </Space>
            <Descriptions bordered size="small" column={2}>
              <Descriptions.Item label="Период">{formatPeriodMonth(detail.period_month)}</Descriptions.Item>
              <Descriptions.Item label="Тип">{detail.kind ? PAYROLL_KIND_LABELS[detail.kind] : '-'}</Descriptions.Item>
              <Descriptions.Item label="Источник">{detail.source === 'portal' ? 'Портал' : 'n8n'}</Descriptions.Item>
              <Descriptions.Item label="Режим выплат">
                {detail.payout_mode === 'portal' ? 'Через портал' : 'Как раньше'}
              </Descriptions.Item>
              <Descriptions.Item label="Итого">{fmtMoney(detail.total_sum)}</Descriptions.Item>
              <Descriptions.Item label="Выплачено">{fmtMoney(detail.paid_total)}</Descriptions.Item>
              <Descriptions.Item label="Остаток">{fmtMoney(detail.remaining_total)}</Descriptions.Item>
              <Descriptions.Item label="Заявка">
                {detail.current_request ? (
                  <Link to={`/requests/${detail.current_request.id}`}>
                    #{detail.current_request.id} · {detail.current_request.status}
                  </Link>
                ) : (
                  '-'
                )}
              </Descriptions.Item>
              {detail.closed_underpaid_at ? (
                <Descriptions.Item label="Закрыто с недоплатой" span={2}>
                  {detail.close_comment}
                </Descriptions.Item>
              ) : null}
            </Descriptions>

            <Space wrap>
              {canEdit ? <Button onClick={() => setEditOpen(true)}>Редактировать</Button> : null}
              {canAccept ? (
                <Button type="primary" onClick={handleAccept}>
                  Принять
                </Button>
              ) : null}
              {canCancel ? (
                <Button danger onClick={handleCancel}>
                  Отменить
                </Button>
              ) : null}
              <Button onClick={() => void handleCopy()}>Скопировать</Button>
              {canPay ? (
                <Button type="primary" onClick={() => setPayoutOpen(true)}>
                  Создать расход
                </Button>
              ) : null}
              {canCloseUnderpaid ? (
                <Button onClick={() => setUnderpaidOpen(true)}>Закрыть с недоплатой</Button>
              ) : null}
            </Space>

            {showPayoutReasonAlert ? <Alert type="info" showIcon message={state?.reason} /> : null}

            {state ? (
              <>
                <Typography.Title level={5}>Сотрудники</Typography.Title>
                <Table
                  rowKey="employee_id"
                  size="small"
                  columns={employeeColumns}
                  dataSource={state.employees}
                  pagination={false}
                />
              </>
            ) : null}

            {state && state.expenses.length > 0 ? (
              <>
                <Typography.Title level={5}>Расходы кассы</Typography.Title>
                <Table
                  rowKey="cash_expense_id"
                  size="small"
                  columns={expenseColumns}
                  dataSource={state.expenses}
                  pagination={false}
                />
              </>
            ) : null}

            <Typography.Title level={5}>Строки</Typography.Title>
            <Table<PayrollDocumentLineDto>
              rowKey="id"
              size="small"
              columns={lineColumns}
              dataSource={detail.lines || []}
              pagination={false}
            />
          </>
        ) : null}
      </Space>

      {detail ? (
        <PayrollDocumentFormModal
          open={editOpen}
          onClose={() => setEditOpen(false)}
          onSaved={() => void reload()}
          initial={detail}
        />
      ) : null}

      <PayrollPayoutModal
        open={payoutOpen}
        onClose={() => setPayoutOpen(false)}
        onDone={() => void reload()}
        documentId={detail?.id}
      />

      <Modal
        title="Закрыть с недоплатой"
        open={underpaidOpen}
        onCancel={() => {
          setUnderpaidOpen(false)
          setUnderpaidComment('')
        }}
        onOk={() => void handleCloseUnderpaid()}
        okText="Закрыть"
        cancelText="Отмена"
        confirmLoading={underpaidSaving}
        okButtonProps={{ disabled: !underpaidComment.trim() }}
        destroyOnClose
      >
        <Input.TextArea
          rows={3}
          placeholder="Комментарий (обязательно)"
          value={underpaidComment}
          onChange={(e) => setUnderpaidComment(e.target.value)}
        />
      </Modal>
    </Card>
  )
}
