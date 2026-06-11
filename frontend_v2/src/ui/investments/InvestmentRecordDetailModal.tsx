import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Card, Descriptions, Divider, Modal, Skeleton, Space, Tag, Typography } from 'antd'

import {
  getInvestReturnApprovals,
  getProjectInvestmentApprovals,
  type InvestmentApprovalItem,
  type InvestReturnRow,
  type ProjectInvestmentRow,
} from '../../lib/api'
import { asMoney, dateText } from './utils'

type RecordKind = 'project' | 'return'

type Props = {
  open: boolean
  onCancel: () => void
  kind: RecordKind | null
  record: ProjectInvestmentRow | InvestReturnRow | null
  companyLabel: (id: number | null) => string
  usesCompanies: boolean
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
  if (!value) return '—'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '—'
  return dateTimeFormatterTashkent.format(parsed)
}

function decisionKey(decision?: string | null): string {
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
  if (key === 'serial') return 'проверка'
  if (key === 'confirmation') return 'подтверждение'
  if (key === 'notification') return 'уведомление'
  return stepType || '—'
}

function accrualMonthLabel(iso: string | undefined): string {
  if (!iso || iso.length < 7) return '—'
  const [y, m] = iso.slice(0, 10).split('-')
  if (!y || !m) return '—'
  return `${m}.${y}`
}

function renderApprovalGroup(title: string, items: InvestmentApprovalItem[]) {
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
              {item.decision_comment?.trim() ? (
                <Typography.Text type="secondary">{item.decision_comment.trim()}</Typography.Text>
              ) : null}
              <Typography.Text type="secondary">Дата решения: {formatDateTime(item.decided_at)}</Typography.Text>
            </Space>
          </Card>
        ))
      )}
    </Space>
  )
}

function currentApprovalSummary(approvals: InvestmentApprovalItem[], confirmed: boolean): string {
  if (confirmed) return 'Подтверждена'
  const rejected = approvals.find((a) => decisionKey(a.decision) === 'rejected')
  if (rejected) {
    return `Отклонена · этап ${rejected.step} (${translateStepType(rejected.step_type)})`
  }
  const pending = approvals
    .filter((a) => decisionKey(a.decision) === 'pending')
    .sort((a, b) => a.step - b.step)[0]
  if (pending) {
    return `На согласовании · этап ${pending.step} (${translateStepType(pending.step_type)})`
  }
  if (approvals.length === 0) return 'Без этапов согласования'
  return 'На согласовании'
}

function summaryTagColor(summary: string, confirmed: boolean): string {
  if (confirmed) return 'success'
  if (summary.startsWith('Отклонена')) return 'error'
  if (summary.startsWith('На согласовании')) return 'warning'
  return 'default'
}

export function InvestmentRecordDetailModal({
  open,
  onCancel,
  kind,
  record,
  companyLabel,
  usesCompanies,
}: Props) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [approvals, setApprovals] = useState<InvestmentApprovalItem[]>([])

  const loadApprovals = useCallback(async () => {
    if (!record || !kind) {
      setApprovals([])
      return
    }
    setLoading(true)
    setError(null)
    try {
      const rows =
        kind === 'project'
          ? await getProjectInvestmentApprovals(record.id)
          : await getInvestReturnApprovals(record.id)
      setApprovals(rows)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Не удалось загрузить этапы согласования')
      setApprovals([])
    } finally {
      setLoading(false)
    }
  }, [kind, record])

  useEffect(() => {
    if (!open || !record || !kind) {
      setApprovals([])
      setError(null)
      return
    }
    void loadApprovals()
  }, [open, record, kind, loadApprovals])

  const approvedApprovals = useMemo(
    () => approvals.filter((a) => decisionKey(a.decision) === 'approved'),
    [approvals],
  )
  const rejectedApprovals = useMemo(
    () => approvals.filter((a) => decisionKey(a.decision) === 'rejected'),
    [approvals],
  )
  const pendingApprovals = useMemo(
    () => approvals.filter((a) => decisionKey(a.decision) === 'pending'),
    [approvals],
  )

  const title =
    kind === 'project'
      ? record
        ? `Заявка на вложение #${record.id}`
        : 'Заявка на вложение'
      : record
        ? `Выплата #${record.id}`
        : 'Выплата'

  const confirmed = Boolean(record?.confirmed)
  const approvalSummary = currentApprovalSummary(approvals, confirmed)

  const projectRecord = kind === 'project' ? (record as ProjectInvestmentRow | null) : null
  const returnRecord = kind === 'return' ? (record as InvestReturnRow | null) : null

  return (
    <Modal open={open} title={title} footer={null} onCancel={onCancel} width={760} destroyOnClose>
      {record ? (
        <>
          <Space wrap style={{ marginBottom: 12 }}>
            <Tag color={summaryTagColor(approvalSummary, confirmed)}>{approvalSummary}</Tag>
            {confirmed ? <Tag color="success">Подтверждена</Tag> : <Tag color="warning">Не подтверждена</Tag>}
          </Space>
          <Descriptions bordered size="small" column={1}>
            <Descriptions.Item label="ID">{record.id}</Descriptions.Item>
            {usesCompanies ? (
              <Descriptions.Item label="Компания">{companyLabel(record.company)}</Descriptions.Item>
            ) : null}
            <Descriptions.Item label="Дата">{dateText(record.date)}</Descriptions.Item>
            {returnRecord ? (
              <Descriptions.Item label="Месяц начисления">
                {accrualMonthLabel(returnRecord.billing_date)}
              </Descriptions.Item>
            ) : null}
            <Descriptions.Item label="Сумма">
              {`${asMoney(projectRecord?.amount ?? returnRecord?.sum ?? 0)} ${record.currency}`}
            </Descriptions.Item>
            {returnRecord?.sum_uzs != null && returnRecord.sum_uzs !== '' ? (
              <Descriptions.Item label="Сум (UZS)">{asMoney(returnRecord.sum_uzs)}</Descriptions.Item>
            ) : null}
            {returnRecord?.type ? <Descriptions.Item label="Тип">{returnRecord.type}</Descriptions.Item> : null}
            {returnRecord?.recipient ? (
              <Descriptions.Item label="Получатель">{returnRecord.recipient}</Descriptions.Item>
            ) : null}
            <Descriptions.Item label="Комментарий">{record.comment?.trim() || '—'}</Descriptions.Item>
            <Descriptions.Item label="Создано">{formatDateTime(record.created_at)}</Descriptions.Item>
          </Descriptions>
        </>
      ) : null}
      {loading ? <Skeleton active style={{ marginTop: 12 }} /> : null}
      {error ? <Alert type="error" showIcon message={error} style={{ marginTop: 12 }} /> : null}
      {!loading && record ? (
        <>
          <Divider />
          <Space direction="vertical" size={12} style={{ display: 'flex' }}>
            {renderApprovalGroup(`Одобрено (${approvedApprovals.length})`, approvedApprovals)}
            {renderApprovalGroup(`Отклонено (${rejectedApprovals.length})`, rejectedApprovals)}
            {renderApprovalGroup(`В ожидании (${pendingApprovals.length})`, pendingApprovals)}
          </Space>
        </>
      ) : null}
    </Modal>
  )
}
