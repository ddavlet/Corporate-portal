import { useEffect, useMemo, useState } from 'react'
import { Alert, Card, Col, Row, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import { SETTINGS_MODULES } from '../settings/settingsModules'
import { getSettingsAccess } from '../lib/api'

export function SettingsPage() {
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)
  const [canOpenSettings, setCanOpenSettings] = useState<boolean | null>(null)
  const [access, setAccess] = useState<{
    can_manage_tenant_settings: boolean
    can_manage_requests_settings: boolean
    can_manage_wallet_settings: boolean
  } | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const data = await getSettingsAccess()
        if (cancelled) return
        setCanOpenSettings(Boolean(data.can_open_settings))
        setAccess({
          can_manage_tenant_settings: Boolean(data.can_manage_tenant_settings),
          can_manage_requests_settings: Boolean(data.can_manage_requests_settings),
          can_manage_wallet_settings: Boolean(data.can_manage_wallet_settings),
        })
      } catch (e: unknown) {
        if (cancelled) return
        setCanOpenSettings(false)
        setError(e instanceof Error ? e.message : 'Не удалось проверить доступы')
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const visibleModules = useMemo(() => {
    if (!access) return []
    return SETTINGS_MODULES.filter((m) => {
      if (m.path === '/settings/tenant-integration-config') {
        return access.can_manage_tenant_settings
      }
      if (m.path === '/settings/request-form-config' || m.path === '/settings/request-approval-config') {
        return access.can_manage_requests_settings
      }
      if (m.path === '/settings/cash-registers') {
        return access.can_manage_wallet_settings
      }
      if (m.path === '/settings/users-roles') {
        return access.can_manage_tenant_settings
      }
      if (m.path === '/settings/investment-form-config' || m.path === '/settings/investment-approval-config') {
        return access.can_manage_requests_settings
      }
      if (m.path === '/settings/pnl-report-config') {
        return access.can_manage_tenant_settings
      }
      return false
    })
  }, [access])

  return (
    <div>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Настройки
      </Typography.Title>
      <Typography.Paragraph type="secondary">
        Модули с отдельными страницами конфигурации. Список можно расширять.
      </Typography.Paragraph>
      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} /> : null}
      {canOpenSettings === false ? <Alert type="warning" showIcon message="У вас нет доступа к настройкам." /> : null}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        {visibleModules.map((m) => (
          <Col xs={24} sm={12} lg={8} key={m.key}>
            <a
              href={m.path}
              style={{ display: 'block', color: 'inherit' }}
              onClick={(event) => {
                if (
                  event.button === 0 &&
                  !event.metaKey &&
                  !event.ctrlKey &&
                  !event.shiftKey &&
                  !event.altKey
                ) {
                  event.preventDefault()
                  navigate(m.path)
                }
              }}
            >
              <Card hoverable title={m.title} extra={m.icon} style={{ height: '100%' }}>
                <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                  {m.description}
                </Typography.Paragraph>
              </Card>
            </a>
          </Col>
        ))}
      </Row>
    </div>
  )
}
