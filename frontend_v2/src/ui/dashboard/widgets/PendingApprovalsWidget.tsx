import { Button, Card, Empty, Space, Typography } from 'antd'
import type { PendingApprovalItem } from './types'

type PendingApprovalsWidgetProps = {
  items: PendingApprovalItem[]
  loading?: boolean
  busy?: boolean
  onApprove: (item: PendingApprovalItem) => void | Promise<void>
  onReject: (item: PendingApprovalItem) => void | Promise<void>
  onPayout: (item: PendingApprovalItem) => void | Promise<void>
}

export function PendingApprovalsWidget({ items, loading, busy, onApprove, onReject, onPayout }: PendingApprovalsWidgetProps) {
  return (
    <Card title="Ожидающие мое согласование" loading={loading}>
      {!items.length ? (
        <Empty description="Нет заявок для согласования" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <Space direction="vertical" size={12} style={{ display: 'flex' }}>
          {items.map((item) => (
            <Card key={`${item.requestId}-${item.step}`} size="small">
              <Space direction="vertical" size={8} style={{ display: 'flex' }}>
                <Typography.Text strong>{item.title}</Typography.Text>
                <Typography.Text type="secondary">
                  Сумма: {item.amountText} {item.currency || ''}
                </Typography.Text>
                <Typography.Text type="secondary">Шаг: {item.step}</Typography.Text>
                <Space wrap>
                  {item.stepType === 'payment' && String(item.paymentActionMode || '').toLowerCase() === 'webapp' ? (
                    <Button type="primary" loading={busy} onClick={() => void onPayout(item)}>
                      Выплатить
                    </Button>
                  ) : (
                    <Button type="primary" loading={busy} onClick={() => void onApprove(item)}>
                      Одобрить
                    </Button>
                  )}
                  <Button danger loading={busy} onClick={() => void onReject(item)}>
                    Отклонить
                  </Button>
                </Space>
              </Space>
            </Card>
          ))}
        </Space>
      )}
    </Card>
  )
}
