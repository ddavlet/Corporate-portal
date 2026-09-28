import { SettingOutlined } from '@ant-design/icons'
import { Button, Drawer } from 'antd'

type Props = {
  open: boolean
  rules: { label: string; text: string }[]
  isAdmin: boolean
  onClose: () => void
  onOpenSettings: () => void
  fullScreen?: boolean
}

export function MethodologyDrawer({ open, rules, isAdmin, onClose, onOpenSettings, fullScreen = false }: Props) {
  return (
    <Drawer open={open} onClose={onClose} width={fullScreen ? '100%' : 560} title="Как считается отчёт">
      <dl className="rp-rules">
        {rules.map((rule) => (
          <div key={rule.label}>
            <dt>{rule.label}</dt>
            <dd>{rule.text}</dd>
          </div>
        ))}
      </dl>
      {isAdmin ? (
        <Button icon={<SettingOutlined />} onClick={onOpenSettings}>
          Изменить настройки отчёта
        </Button>
      ) : null}
    </Drawer>
  )
}
