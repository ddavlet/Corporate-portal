import { useEffect, useState } from 'react'
import { Alert, Button, Card, Divider, InputNumber, Select, Skeleton, Space, Switch, Typography, message } from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'

import {
  getInvestNotificationConfig,
  updateInvestNotificationConfig,
  type InvestNotificationConfigResponse,
} from '../../lib/api'

export function InvestmentNotificationConfigPage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<InvestNotificationConfigResponse | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setError(null)
      try {
        const cfg = await getInvestNotificationConfig()
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

  const save = async () => {
    if (!data) return
    if (!data.responsible_user_id) {
      message.warning('Выберите ответственного пользователя')
      return
    }
    setSaving(true)
    setError(null)
    try {
      const next = await updateInvestNotificationConfig({
        responsible_user_id: data.responsible_user_id,
        days_before: data.days_before,
        overdue_notify_every_days: data.overdue_notify_every_days,
        is_active: data.is_active,
      })
      setData(next)
      message.success('Сохранено')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Ошибка сохранения')
    } finally {
      setSaving(false)
    }
  }

  const candidates = data?.approver_candidates ?? []

  return (
    <Card>
      <Button type="link" icon={<ArrowLeftOutlined />} onClick={() => navigate('/settings')} style={{ padding: 0 }}>
        Назад к настройкам
      </Button>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Инвестиции — уведомления о выплатах
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        Ответственный получает уведомление в Telegram перед каждой плановой выплатой по инвестициям. Прямо из
        сообщения он может создать заявку на платёж в один клик.
      </Typography.Paragraph>

      <Divider />
      {loading ? <Skeleton active /> : null}
      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} /> : null}

      {!loading && data ? (
        <Space direction="vertical" size={16} style={{ display: 'flex' }}>
          <Space align="center">
            <Switch checked={data.is_active} onChange={(v) => setData({ ...data, is_active: v })} />
            <Typography.Text>Уведомления включены</Typography.Text>
          </Space>

          <div>
            <Typography.Text strong>Ответственный пользователь</Typography.Text>
            <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
              Этот пользователь получает уведомления в Telegram и указывается как создатель заявок на платёж.
              У него должен быть настроен Telegram chat ID.
            </Typography.Paragraph>
            <Select
              style={{ width: 320 }}
              placeholder="Выберите пользователя"
              value={data.responsible_user_id ?? undefined}
              onChange={(v: number) => setData({ ...data, responsible_user_id: v })}
              options={candidates.map((c) => ({ value: c.id, label: c.label || c.username }))}
              showSearch
              filterOption={(input, option) =>
                String(option?.label ?? '').toLowerCase().includes(input.toLowerCase())
              }
            />
          </div>

          <div>
            <Typography.Text strong>Уведомлять за N дней до выплаты</Typography.Text>
            <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
              Уведомление отправляется один раз в день по каждой неоплаченной выплате в этом окне.
            </Typography.Paragraph>
            <InputNumber
              min={1}
              max={365}
              value={data.days_before}
              onChange={(v) => setData({ ...data, days_before: v ?? 3 })}
              addonAfter="дн."
            />
          </div>

          <div>
            <Typography.Text strong>Уведомления о просрочке (каждые N дней)</Typography.Text>
            <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
              Уведомление отправляется каждые N дней, пока выплата не оплачена. 0 — отключено.
            </Typography.Paragraph>
            <InputNumber
              min={0}
              max={365}
              value={data.overdue_notify_every_days}
              onChange={(v) => setData({ ...data, overdue_notify_every_days: v ?? 0 })}
              addonAfter="дн."
            />
          </div>

          <Button type="primary" onClick={() => void save()} loading={saving} disabled={!data.responsible_user_id}>
            Сохранить
          </Button>
        </Space>
      ) : null}
    </Card>
  )
}
