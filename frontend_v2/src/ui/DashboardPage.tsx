import { useEffect, useState } from 'react'
import { Alert, Card, Col, Row, Skeleton, Space, Tag, Typography } from 'antd'
import { apiFetch } from '../lib/api'

type ModuleRow = {
  module_key: string
  display_name: string
  tenant_enabled: boolean
  user_allowed: boolean
  effective_enabled: boolean
}

export function DashboardPage() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [modules, setModules] = useState<ModuleRow[]>([])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setError(null)
      try {
        const res = await apiFetch('/api/modules/')
        if (!res.ok) throw new Error(`Ошибка HTTP ${res.status}`)
        const data = (await res.json()) as { modules: ModuleRow[] }
        if (!cancelled) setModules(data.modules || [])
      } catch (e: any) {
        if (!cancelled) setError(e?.message || 'Не удалось загрузить модули')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Card>
        <Typography.Title level={4} style={{ marginTop: 0 }}>
          Панель модулей
        </Typography.Title>
        <Typography.Text type="secondary">
          Текущий хост: <span className="mono">{location.host}</span>
        </Typography.Text>
      </Card>

      {loading ? <Skeleton active /> : null}
      {error ? <Alert type="error" showIcon message="Не удалось загрузить модули" description={error} /> : null}

      <Row gutter={[16, 16]}>
        {(modules || []).map((m) => (
          <Col key={m.module_key} xs={24} md={12}>
            <Card
              title={m.display_name}
              extra={<Tag color={m.effective_enabled ? 'green' : 'default'}>{m.effective_enabled ? 'Доступен' : 'Отключен'}</Tag>}
            >
              <Space direction="vertical" size={4}>
                <Typography.Text type="secondary">
                  Ключ: <span className="mono">{m.module_key}</span>
                </Typography.Text>
                <Typography.Text type="secondary">
                  Включен у тенанта: <span className="mono">{String(m.tenant_enabled)}</span>
                </Typography.Text>
                <Typography.Text type="secondary">
                  Разрешен пользователю: <span className="mono">{String(m.user_allowed)}</span>
                </Typography.Text>
              </Space>
            </Card>
          </Col>
        ))}
      </Row>

      {!loading && !modules.length ? <Alert type="info" showIcon message="Список модулей пуст." /> : null}
    </Space>
  )
}

