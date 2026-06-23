import { Badge, Button, Card, Empty, List, Skeleton, Space, Tag, Tooltip, Typography } from 'antd'
import { ArrowRightOutlined } from '@ant-design/icons'
import type { InProgressRequestRow } from '../../../lib/api'
import { getRequestStatusColor } from '../../../lib/requestUtils'
import type { PendingApprovalItem } from './types'

function statusLabel(status: string): string {
  const s = String(status || '').trim().toUpperCase()
  if (s === 'DRAFT') return 'Черновик'
  if (s === 'APPROVED') return 'Согласована'
  const n = Number(s)
  if (Number.isFinite(n) && n >= 1 && n <= 5) return `Этап ${n} из 5`
  return status
}

function statusHint(status: string): string {
  const s = String(status || '').trim().toUpperCase()
  if (s === 'DRAFT') return 'Заявка создана, но ещё не отправлена на согласование'
  if (s === 'APPROVED') return 'Все этапы согласованы — ожидает оплаты'
  const n = Number(s)
  if (Number.isFinite(n) && n >= 1 && n <= 5) return `Ожидает согласования на этапе ${n}`
  return ''
}

type Props = {
  requests: InProgressRequestRow[]
  loading: boolean
  error?: string | null
  pendingApprovals: PendingApprovalItem[]
  onOpen: (id: number) => void
}

export function ActiveRequestsWidget({ requests, loading, error, pendingApprovals, onOpen }: Props) {
  const myPendingByRequestId = new Map(pendingApprovals.map((a) => [a.requestId, a]))

  return (
    <Card
      title={
        <Space>
          Заявки в процессе
          <Badge count={requests.length} showZero color="#1677ff" />
        </Space>
      }
      extra={
        <Tooltip title="Заявки, не завершённые оплатой или отклонением">
          <Typography.Text type="secondary" style={{ fontSize: 12, cursor: 'default' }}>
            Кроме PAYED и REJECTED
          </Typography.Text>
        </Tooltip>
      }
    >
      {loading ? <Skeleton active /> : null}
      {!loading && error ? (
        <Typography.Text type="danger">{error}</Typography.Text>
      ) : null}
      {!loading && !error && requests.length === 0 ? (
        <Empty description="Нет активных заявок" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : null}
      {!loading && !error && requests.length > 0 ? (
        <List<InProgressRequestRow>
          dataSource={requests}
          pagination={requests.length > 8 ? { pageSize: 8, size: 'small', showSizeChanger: false } : false}
          renderItem={(req) => {
            const hint = statusHint(req.status)
            const myApproval = myPendingByRequestId.get(req.id)
            const amountText = `${Number(req.amount).toLocaleString('ru-RU')} ${req.currency || ''}`

            return (
              <List.Item
                key={req.id}
                style={{ cursor: 'pointer' }}
                onClick={() => onOpen(req.id)}
                actions={[
                  <Button
                    key="open"
                    type="link"
                    size="small"
                    icon={<ArrowRightOutlined />}
                    onClick={(e) => { e.stopPropagation(); onOpen(req.id) }}
                  >
                    Открыть
                  </Button>,
                ]}
              >
                <List.Item.Meta
                  title={
                    <Space wrap size={[8, 4]}>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        #{req.id}
                      </Typography.Text>
                      <Typography.Text strong style={{ fontSize: 14 }}>
                        {req.title || 'Заявка'}
                      </Typography.Text>
                      <Tooltip title={hint}>
                        <Tag color={getRequestStatusColor(req.status)} style={{ cursor: 'help' }}>
                          {statusLabel(req.status)}
                        </Tag>
                      </Tooltip>
                      <Typography.Text type="secondary">{amountText}</Typography.Text>
                    </Space>
                  }
                  description={
                    <Space direction="vertical" size={4} style={{ display: 'flex' }}>
                      {req.payment_purpose ? (
                        <Typography.Text>
                          <Typography.Text type="secondary">Назначение: </Typography.Text>
                          {req.payment_purpose}
                        </Typography.Text>
                      ) : null}
                      {req.description ? (
                        <Typography.Text type="secondary" ellipsis={{ tooltip: req.description }}>
                          {req.description}
                        </Typography.Text>
                      ) : null}
                      <Space wrap size={[6, 4]}>
                        {req.category ? <Tag style={{ margin: 0 }}>{req.category}</Tag> : null}
                        {req.vendor ? (
                          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                            Поставщик: {req.vendor}
                          </Typography.Text>
                        ) : null}
                        {req.requester_username ? (
                          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                            Заявитель: {req.requester_username}
                          </Typography.Text>
                        ) : null}
                        {myApproval ? (
                          <Tag color="orange" style={{ margin: 0 }}>
                            Ждёт вашего согласования (этап {myApproval.step})
                          </Tag>
                        ) : hint ? (
                          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                            {hint}
                          </Typography.Text>
                        ) : null}
                      </Space>
                    </Space>
                  }
                />
              </List.Item>
            )
          }}
        />
      ) : null}
    </Card>
  )
}
