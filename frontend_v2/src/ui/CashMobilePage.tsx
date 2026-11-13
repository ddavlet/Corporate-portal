import { useNavigate } from 'react-router-dom'
import { Button } from 'antd'
import { SwapOutlined } from '@ant-design/icons'

import { CASH_TRANSFER_PATH } from './cashMobileNav'
import { MobileStateWidget } from './MobileStateWidget'
import { useMobileHeader } from './mobileShell'
import { useModuleAccess } from './moduleAccess'
import { MobileActionsTheme } from './requests/mobileActionsTheme'

/**
 * `/cash` on a phone: one action instead of the desktop lists — «Перевести между кассами», a full-screen form on its
 * own address. Without the «cash» module — «Раздел недоступен». The server still checks the rights.
 */
export function CashMobilePage() {
  useMobileHeader({ title: 'Касса' })
  const navigate = useNavigate()
  const { loading, hasAccess } = useModuleAccess()

  if (loading) return <MobileStateWidget state="loading" rows={1} />

  if (!hasAccess('cash')) {
    return (
      <MobileStateWidget state="empty" title="Раздел недоступен" description="Модуль «Касса» не включён для вашей роли." />
    )
  }

  return (
    <MobileActionsTheme>
      <div style={{ display: 'grid', gap: 12 }}>
        <Button
          type="primary"
          block
          size="large"
          icon={<SwapOutlined />}
          style={{ height: 48 }}
          onClick={() => navigate(CASH_TRANSFER_PATH)}
        >
          Перевести между кассами
        </Button>
      </div>
    </MobileActionsTheme>
  )
}
