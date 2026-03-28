import { Alert, Card, Descriptions, Divider, Modal, Skeleton, Space, Tag, Typography } from 'antd'

export type ApprovalItem = {
  id: number
  step: number
  step_type: string
  decision: string
  comment?: string | null
  decided_at?: string | null
  approver_username?: string | null
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
  payment_purpose?: string
  file_link?: string | null
  requester: number | null
  requester_username?: string | null
  submitted_at: string
  billing_date: string
  expense_id?: string | null
  expense_link?: {
    module?: string
    expense_type?: string
    id?: number | string
    url?: string | null
  } | null
  approvals: ApprovalItem[]
}

const dateFormatterTashkent = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  timeZone: 'Asia/Tashkent',
})

function formatDateDDMMYYYY(value?: string | null): string {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '-'
  return dateFormatterTashkent.format(parsed)
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
                <Tag color={getDecisionColor(item.decision)}>{String(item.decision || '').toUpperCase()}</Tag>
              </Space>
              <Typography.Text type="secondary">{item.comment || 'without comment'}</Typography.Text>
              <Typography.Text type="secondary">{formatDateDDMMYYYY(item.decided_at)}</Typography.Text>
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
}

export function RequestDetailContent({ detail, loading = false, error = null, actions = null }: RequestDetailContentProps) {
  const approvals = detail?.approvals || []
  const approvedApprovals = approvals.filter((a) => decisionKey(a.decision) === 'approved')
  const rejectedApprovals = approvals.filter((a) => decisionKey(a.decision) === 'rejected')
  const pendingApprovals = approvals.filter((a) => decisionKey(a.decision) === 'pending')

  return (
    <>
      {actions ? <Space style={{ marginBottom: 12 }}>{actions}</Space> : null}
      {detail ? (
        <Descriptions bordered size="small" column={1}>
          <Descriptions.Item label="Название">{detail.title || '-'}</Descriptions.Item>
          <Descriptions.Item label="Статус">
            <Tag color={getStatusColor(detail.status)}>{detail.status}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Сумма">{`${Number(detail.amount).toLocaleString('ru-RU')} ${detail.currency}`}</Descriptions.Item>
          <Descriptions.Item label="Категория">{detail.category || '-'}</Descriptions.Item>
          <Descriptions.Item label="Поставщик">{detail.vendor || '-'}</Descriptions.Item>
          <Descriptions.Item label="Назначение платежа">{detail.payment_purpose || '-'}</Descriptions.Item>
          <Descriptions.Item label="Описание">{detail.description || '-'}</Descriptions.Item>
          <Descriptions.Item label="Заявитель">
            {detail.requester_username || (detail.requester ? `User #${detail.requester}` : '-')}
          </Descriptions.Item>
          <Descriptions.Item label="Отправлено">{formatDateDDMMYYYY(detail.submitted_at)}</Descriptions.Item>
          <Descriptions.Item label="Дата биллинга">{formatDateDDMMYYYY(detail.billing_date)}</Descriptions.Item>
          <Descriptions.Item label="Файл">
            {detail.file_link ? (
              <Typography.Link href={detail.file_link} target="_blank" rel="noreferrer">
                Открыть файл
              </Typography.Link>
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
