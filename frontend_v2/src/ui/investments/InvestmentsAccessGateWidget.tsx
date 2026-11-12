import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, theme } from 'antd'
import { CloseOutlined } from '@ant-design/icons'

import { MobileStateWidget } from '../MobileStateWidget'
import { useModuleAccess } from '../moduleAccess'
import { closeToInvestments } from './investmentsMobileNav'

type Props = {
  /** The form's heading, kept on the loading and «нет прав» screens. */
  title: string
  testId: string
  children: ReactNode
}

/**
 * A full-screen investments form opened by a direct link: while the modules load — a skeleton, without the
 * «investments» module — «Раздел недоступен» with «Закрыть»; the form (and its requests) only with access.
 * The server still checks the rights; this only mirrors them.
 */
export function InvestmentsAccessGateWidget({ title, testId, children }: Props) {
  const { token } = theme.useToken()
  const navigate = useNavigate()
  const { loading, hasAccess } = useModuleAccess()

  if (!loading && hasAccess('investments')) return <>{children}</>

  const close = () => closeToInvestments(navigate)
  return (
    <div className="m-fullscreen m-root" data-testid={testId} style={{ background: token.colorBgLayout }}>
      <header
        className="m-header"
        style={{ position: 'static', background: token.colorBgContainer, borderBottom: `1px solid ${token.colorBorderSecondary}` }}
      >
        <Button type="text" className="m-header__button" icon={<CloseOutlined />} aria-label="Закрыть" onClick={close} />
        <h1 className="m-header__title m-ellipsis">{title}</h1>
      </header>
      <div className="m-fullscreen__body">
        <div style={{ padding: 16 }}>
          {loading ? (
            <MobileStateWidget state="loading" rows={2} />
          ) : (
            <MobileStateWidget
              state="empty"
              title="Раздел недоступен"
              description="Модуль «Инвестиции» не включён для вашей роли."
              action={<Button onClick={close}>Закрыть</Button>}
            />
          )}
        </div>
      </div>
    </div>
  )
}
