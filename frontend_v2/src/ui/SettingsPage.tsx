import { Card, Col, Row, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import { SETTINGS_MODULES } from '../settings/settingsModules'

export function SettingsPage() {
  const navigate = useNavigate()

  return (
    <div>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Настройки
      </Typography.Title>
      <Typography.Paragraph type="secondary">
        Модули с отдельными страницами конфигурации. Список можно расширять.
      </Typography.Paragraph>
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        {SETTINGS_MODULES.map((m) => (
          <Col xs={24} sm={12} lg={8} key={m.key}>
            <Card
              hoverable
              title={m.title}
              extra={m.icon}
              onClick={() => navigate(m.path)}
              style={{ height: '100%' }}
            >
              <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                {m.description}
              </Typography.Paragraph>
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  )
}
