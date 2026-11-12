import { Badge, Button } from 'antd'
import { BellOutlined } from '@ant-design/icons'

type Props = {
  count: number
  onClick: () => void
  /** `touch`: a 44×44 target for the phone header. */
  size?: 'default' | 'touch'
}

const TOUCH_SIZE = 44

/** Header bell: a red badge with the number of objects waiting on the user; no badge at zero. */
export function NotificationsBellWidget({ count, onClick, size = 'default' }: Props) {
  const label = count > 0 ? `Уведомления: требуется действие (${count})` : 'Уведомления'
  const touch = size === 'touch'
  return (
    <Badge
      count={count}
      size="small"
      overflowCount={99}
      offset={touch ? [-8, 8] : [-4, 4]}
      data-testid="notifications-bell-badge"
    >
      <Button
        icon={<BellOutlined />}
        aria-label={label}
        title={label}
        onClick={onClick}
        {...(touch ? { type: 'text' as const, style: { width: TOUCH_SIZE, height: TOUCH_SIZE } } : {})}
      />
    </Badge>
  )
}
