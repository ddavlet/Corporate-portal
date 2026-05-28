import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Col, Row, Tooltip, Typography } from 'antd'
import { ArrowLeftOutlined, LockOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { SETTINGS_GROUPS, SETTINGS_MODULES } from '../settings/settingsModules'
import { getSettingsAccess } from '../lib/api'

export function SettingsPage() {
  const navigate = useNavigate()
  const [selectedGroup, setSelectedGroup] = useState<string | null>(null)
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

  const moduleAccessMap = useMemo(() => {
    if (!access) return new Map<string, boolean>()
    const check = (m: { path: string }): boolean => {
      if (m.path === '/settings/tenant-integration-config') return access.can_manage_tenant_settings
      if (m.path === '/settings/request-form-config' || m.path === '/settings/request-approval-config') return access.can_manage_requests_settings
      if (m.path === '/settings/cash-registers') return access.can_manage_wallet_settings
      if (m.path === '/settings/users-roles') return access.can_manage_tenant_settings
      if (m.path === '/settings/investment-form-config' || m.path === '/settings/investment-approval-config' || m.path === '/settings/investment-project-approval-config' || m.path === '/settings/investment-notification-config') return access.can_manage_requests_settings
      if (m.path === '/settings/pnl-report-config' || m.path === '/settings/cashflow-report-config') return access.can_manage_tenant_settings
      if (m.path === '/settings/telegram-chats') return access.can_manage_tenant_settings
      if (m.path === '/settings/tasks-config') return access.can_manage_tenant_settings
      return false
    }
    return new Map(SETTINGS_MODULES.map((m) => [m.path, check(m)]))
  }, [access])

  const activeGroup = selectedGroup ? SETTINGS_GROUPS.find((g) => g.key === selectedGroup) : null
  const visibleModules = selectedGroup ? SETTINGS_MODULES.filter((m) => m.group === selectedGroup) : []

  if (selectedGroup && activeGroup) {
    return (
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 4 }}>
          <Button
            type="text"
            icon={<ArrowLeftOutlined />}
            onClick={() => setSelectedGroup(null)}
            style={{ padding: '0 8px' }}
          >
            Назад
          </Button>
          <Typography.Title level={4} style={{ margin: 0 }}>
            {activeGroup.label}
          </Typography.Title>
        </div>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
          {activeGroup.description}
        </Typography.Paragraph>
        {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} /> : null}
        <Row gutter={[16, 16]}>
          {visibleModules.map((m) => {
            const canAccess = access ? (moduleAccessMap.get(m.path) ?? false) : null
            if (canAccess === false) {
              return (
                <Col xs={24} sm={12} lg={8} key={m.key}>
                  <Tooltip title="Нет доступа. Обратитесь к администратору.">
                    <Card
                      title={m.title}
                      extra={<LockOutlined style={{ color: '#bfbfbf' }} />}
                      style={{ height: '100%', opacity: 0.55, cursor: 'not-allowed' }}
                    >
                      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                        {m.description}
                      </Typography.Paragraph>
                    </Card>
                  </Tooltip>
                </Col>
              )
            }
            return (
              <Col xs={24} sm={12} lg={8} key={m.key}>
                <a
                  href={m.path}
                  style={{ display: 'block', color: 'inherit' }}
                  onClick={(event) => {
                    if (event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) {
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
            )
          })}
        </Row>
      </div>
    )
  }

  return (
    <div>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Настройки
      </Typography.Title>
      <Typography.Paragraph type="secondary">
        Выберите раздел, чтобы перейти к его настройкам.
      </Typography.Paragraph>
      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} /> : null}
      {canOpenSettings === false ? <Alert type="warning" showIcon message="У вас нет доступа к настройкам." /> : null}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        {SETTINGS_GROUPS.map((group) => (
          <Col xs={24} sm={12} lg={8} key={group.key}>
            <Card
              hoverable
              title={group.label}
              extra={group.icon}
              style={{ height: '100%', cursor: 'pointer' }}
              onClick={() => setSelectedGroup(group.key)}
            >
              <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                {group.description}
              </Typography.Paragraph>
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  )
}
