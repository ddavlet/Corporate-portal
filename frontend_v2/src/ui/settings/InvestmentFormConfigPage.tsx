import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Checkbox, Divider, Skeleton, Space, Switch, Typography, message } from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'

import {
  getInvestmentFormConfig,
  updateInvestmentFormConfig,
  type InvestmentFormConfigResponse,
} from '../../lib/api'

export function InvestmentFormConfigPage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<InvestmentFormConfigResponse | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setError(null)
      try {
        const cfg = await getInvestmentFormConfig()
        if (!cancelled) setData(cfg)
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Ошибка загрузки')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const choiceOptions = useMemo(
    () => (data?.return_type_choices ?? []).map((c) => ({ label: c.label, value: c.value })),
    [data?.return_type_choices],
  )

  const save = async () => {
    if (!data) return
    if (!data.allowed_return_types.length) {
      message.warning('Выберите хотя бы один тип выплат')
      return
    }
    setSaving(true)
    setError(null)
    try {
      const next = await updateInvestmentFormConfig({
        uses_companies: data.uses_companies,
        allowed_return_types: data.allowed_return_types,
      })
      setData(next)
      message.success('Сохранено')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Ошибка сохранения')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card>
      <Button type="link" icon={<ArrowLeftOutlined />} onClick={() => navigate('/settings')} style={{ padding: 0 }}>
        Назад к настройкам
      </Button>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Инвестиции — форма создания
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        Разрешённые типы выплат при создании фактической выплаты и использование компаний на экране инвестиций.
      </Typography.Paragraph>

      <Divider />
      {loading ? <Skeleton active /> : null}
      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} /> : null}

      {!loading && data ? (
        <Space direction="vertical" size={16} style={{ display: 'flex' }}>
          <Space align="center">
            <Switch checked={data.uses_companies} onChange={(v) => setData({ ...data, uses_companies: v })} />
            <Typography.Text>
              Tenant использует компании (вкладка «Компании», фильтр и поле компании в формах)
            </Typography.Text>
          </Space>

          <div>
            <Typography.Text strong>Разрешённые типы выплат</Typography.Text>
            <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
              В модальном окне «Создать выплату» будут доступны только отмеченные типы; сервер также отклонит другие
              значения.
            </Typography.Paragraph>
            <Checkbox.Group
              options={choiceOptions}
              value={data.allowed_return_types}
              onChange={(vals) => setData({ ...data, allowed_return_types: vals as string[] })}
            />
          </div>

          <Button type="primary" onClick={() => void save()} loading={saving}>
            Сохранить
          </Button>
        </Space>
      ) : null}
    </Card>
  )
}
