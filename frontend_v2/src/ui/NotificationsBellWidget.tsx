import { Badge, Button } from 'antd'
import { BellOutlined } from '@ant-design/icons'

type Props = {
  count: number
  onClick: () => void
}

/** Header bell: a red badge with the number of objects waiting on the user; no badge at zero. */
export function NotificationsBellWidget({ count, onClick }: Props) {
  const label = count > 0 ? `Уведомления: требуется действие (${count})` : 'Уведомления'
  return (
    <Badge count={count} size="small" overflowCount={99} offset={[-4, 4]} data-testid="notifications-bell-badge">
      <Button icon={<BellOutlined />} aria-label={label} title={label} onClick={onClick} />
    </Badge>
  )
}
