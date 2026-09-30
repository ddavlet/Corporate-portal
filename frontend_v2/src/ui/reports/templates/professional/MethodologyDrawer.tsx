import { SettingOutlined } from '@ant-design/icons'
import { Button, Drawer } from 'antd'

type Props = {
  open: boolean
  rules: { label: string; text: string }[]
  onClose: () => void
  /** Opens the report's rules; null for users who may not change them. */
  onOpenSettings: (() => void) | null
  fullScreen?: boolean
}

export function MethodologyDrawer({ open, rules, onClose, onOpenSettings, fullScreen = false }: Props) {
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
      {onOpenSettings ? (
        <Button icon={<SettingOutlined />} onClick={onOpenSettings}>
          Изменить настройки отчёта
        </Button>
      ) : null}
    </Drawer>
  )
}
