import { useEffect, useState } from 'react'
import { Alert, Button, Card, Select, Skeleton, Space, Switch, Typography, message } from 'antd'

import {
  CashDeskConfigUnavailableError,
  getCardTopupNotifyConfig,
  saveCardTopupNotifyConfig,
  type CardTopupNotifyConfigDto,
  type CardTopupNotifyConfigResponse,
  type CardTopupUserOption,
} from '../../lib/cashDeskApi'

function userLabel(u: CardTopupUserOption): string {
  return u.has_telegram ? u.name : `${u.name} (нет Telegram)`
}

/** Блок «Пополнение корпоративной карты» на странице настроек кассы; скрывается, если API недоступен. */
export function CardTopupNotifyWidget() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [hidden, setHidden] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<CardTopupNotifyConfigDto | null>(null)
  const [users, setUsers] = useState<CardTopupUserOption[]>([])

  const apply = (res: CardTopupNotifyConfigResponse) => {
    setData({ is_active: res.is_active, recipient_ids: res.recipient_ids })
    setUsers(res.available_users)
  }

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const res = await getCardTopupNotifyConfig()
        if (!cancelled) apply(res)
      } catch (e: unknown) {
        if (cancelled) return
        if (e instanceof CashDeskConfigUnavailableError) setHidden(true)
        else setError(e instanceof Error ? e.message : 'Ошибка загрузки')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const patch = (next: Partial<CardTopupNotifyConfigDto>) =>
    setData((prev) => (prev ? { ...prev, ...next } : prev))

  const save = async () => {
    if (!data) return
    setSaving(true)
    setError(null)
    try {
      apply(await saveCardTopupNotifyConfig(data))
      message.success('Сохранено')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Ошибка сохранения')
    } finally {
      setSaving(false)
    }
  }

  if (hidden) return null

  return (
    <Card title="Пополнение корпоративной карты">
      <Typography.Paragraph type="secondary">
        Личное сообщение выбранным людям, когда оплачена заявка «Пополнение». Остаток карты — по данным портала на
        момент оплаты.
      </Typography.Paragraph>
      {loading ? <Skeleton active /> : null}
      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} /> : null}

      {!loading && data ? (
        <Space direction="vertical" size={20} style={{ display: 'flex' }}>
          <Space align="center">
            <Switch
              aria-label="Уведомления о пополнении карты"
              checked={data.is_active}
              onChange={(v) => patch({ is_active: v })}
            />
            <Typography.Text>Включено</Typography.Text>
          </Space>

          <div>
            <Typography.Title level={5}>Получатели</Typography.Title>
            <Select
              mode="multiple"
              style={{ width: '100%', maxWidth: 480 }}
              placeholder="Выберите пользователей"
              optionFilterProp="label"
              value={data.recipient_ids}
              onChange={(v: number[]) => patch({ recipient_ids: v })}
              options={users.map((u) => ({ value: u.id, label: userLabel(u) }))}
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
