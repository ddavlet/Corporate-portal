import { useEffect, useState } from 'react'
import { Alert, Button, Card, Divider, Result, Select, Skeleton, Space, Switch, Typography, message } from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'

import {
  CashDeskConfigUnavailableError,
  getCashDeskConfig,
  saveCashDeskConfig,
  type CashDeskConfigDto,
  type CashDeskConfigResponse,
} from '../../lib/cashDeskApi'

type Chats = CashDeskConfigResponse['options']['telegram_chats']

export function CashDeskConfigPage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [unavailable, setUnavailable] = useState(false)
  const [data, setData] = useState<CashDeskConfigDto | null>(null)
  const [chats, setChats] = useState<Chats>([])

  const apply = (res: CashDeskConfigResponse) => {
    setData({ is_active: res.is_active, telegram_chat_id: res.telegram_chat_id })
    setChats(res.options.telegram_chats)
  }

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const res = await getCashDeskConfig()
        if (!cancelled) apply(res)
      } catch (e: unknown) {
        if (cancelled) return
        if (e instanceof CashDeskConfigUnavailableError) setUnavailable(true)
        else setError(e instanceof Error ? e.message : 'Ошибка загрузки')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const patch = (next: Partial<CashDeskConfigDto>) => setData((prev) => (prev ? { ...prev, ...next } : prev))

  const save = async () => {
    if (!data) return
    setSaving(true)
    setError(null)
    try {
      apply(await saveCashDeskConfig(data))
      message.success('Сохранено')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Ошибка сохранения')
    } finally {
      setSaving(false)
    }
  }

  const back = (
    <Button type="link" icon={<ArrowLeftOutlined />} onClick={() => navigate('/settings')} style={{ padding: 0 }}>
      Назад к настройкам
    </Button>
  )

  if (unavailable) {
    return (
      <Card>
        {back}
        <Result status="warning" title="Настройка недоступна" subTitle="Её меняет администратор или директор компании." />
      </Card>
    )
  }

  return (
    <Card>
      {back}
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Касса: уведомления в Telegram
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        При оплате наличной заявки в группу уходит сообщение с остатками касс; перевод между кассами создаёт приход в кассе-получателе
      </Typography.Paragraph>
      <Divider />
      {loading ? <Skeleton active /> : null}
      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} /> : null}

      {!loading && data ? (
        <Space direction="vertical" size={20} style={{ display: 'flex' }}>
          <Space align="center">
            <Switch checked={data.is_active} onChange={(v) => patch({ is_active: v })} />
            <Typography.Text>Включено</Typography.Text>
          </Space>

          <div>
            <Typography.Title level={5}>Кассовая группа</Typography.Title>
            <Select
              style={{ width: 320 }}
              allowClear
              placeholder="Кассовая группа"
              value={data.telegram_chat_id ?? undefined}
              onChange={(v) => patch({ telegram_chat_id: v ?? null })}
              options={chats.map((c) => ({ value: c.id, label: c.name }))}
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
