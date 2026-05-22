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
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load config')
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
      message.warning('Please select a responsible user')
      return
    }
    setSaving(true)
    setError(null)
    try {
      const next = await updateInvestNotificationConfig({
        responsible_user_id: data.responsible_user_id,
        days_before: data.days_before,
        is_active: data.is_active,
      })
      setData(next)
      message.success('Saved')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  const candidates = data?.approver_candidates ?? []

  return (
    <Card>
      <Button type="link" icon={<ArrowLeftOutlined />} onClick={() => navigate('/settings')} style={{ padding: 0 }}>
        Back to settings
      </Button>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Investments — Payout Notifications
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        The responsible user receives a Telegram message before each upcoming investment payout. From the message
        they can create a payment request with one tap.
      </Typography.Paragraph>

      <Divider />
      {loading ? <Skeleton active /> : null}
      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} /> : null}

      {!loading && data ? (
        <Space direction="vertical" size={16} style={{ display: 'flex' }}>
          <Space align="center">
            <Switch checked={data.is_active} onChange={(v) => setData({ ...data, is_active: v })} />
            <Typography.Text>Notifications active</Typography.Text>
          </Space>

          <div>
            <Typography.Text strong>Responsible user</Typography.Text>
            <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
              This user will receive Telegram notifications and will be set as the creator of payment requests.
              They must have a Telegram chat ID configured.
            </Typography.Paragraph>
            <Select
              style={{ width: 320 }}
              placeholder="Select user"
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
            <Typography.Text strong>Notify N days before payout</Typography.Text>
            <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
              A notification is sent once per day for each unpaid payout within this window.
            </Typography.Paragraph>
            <InputNumber
              min={1}
              max={365}
              value={data.days_before}
              onChange={(v) => setData({ ...data, days_before: v ?? 3 })}
              addonAfter="days"
            />
          </div>

          <Button type="primary" onClick={() => void save()} loading={saving} disabled={!data.responsible_user_id}>
            Save
          </Button>
        </Space>
      ) : null}
    </Card>
  )
}
