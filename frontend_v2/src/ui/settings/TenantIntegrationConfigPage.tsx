import { useEffect, useState } from 'react'
import { Alert, Button, Card, Divider, Input, Space, Tag, Typography, message } from 'antd'
import {
  getTenantIntegrationConfig,
  manageMessagingWebhook,
  type TenantIntegrationConfigResponse,
  type TenantIntegrationConfigUpdatePayload,
  updateTenantIntegrationConfig,
} from '../../lib/api'

type FormState = {
  telegram_bot_token: string
  telegram_bot_username: string
  telegram_oidc_client_id: string
  telegram_oidc_client_secret: string
  telegram_oidc_redirect_uri: string
  requests_file_gateway_token: string
  messaging_gateway_feedback_recipient_id: string
  messaging_gateway_feedback_action: string
  messaging_gateway_webhook_connected: boolean
  messaging_gateway_webhook_url: string
  messaging_gateway_webhook_error: string
}

const MASK = '********'

function toFormState(data: TenantIntegrationConfigResponse): FormState {
  return {
    telegram_bot_token: data.telegram_bot_token || '',
    telegram_bot_username: data.telegram_bot_username || '',
    telegram_oidc_client_id: data.telegram_oidc_client_id || '',
    telegram_oidc_client_secret: data.telegram_oidc_client_secret || '',
    telegram_oidc_redirect_uri: data.telegram_oidc_redirect_uri || '',
    requests_file_gateway_token: data.requests_file_gateway_token || '',
    messaging_gateway_feedback_recipient_id:
      data.messaging_gateway_feedback_recipient_id != null ? String(data.messaging_gateway_feedback_recipient_id) : '',
    messaging_gateway_feedback_action: data.messaging_gateway_feedback_action || '',
    messaging_gateway_webhook_connected: Boolean(data.messaging_gateway_webhook_connected),
    messaging_gateway_webhook_url: data.messaging_gateway_webhook_url || '',
    messaging_gateway_webhook_error: data.messaging_gateway_webhook_error || '',
  }
}

export function TenantIntegrationConfigPage() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState<FormState | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getTenantIntegrationConfig()
      setForm(toFormState(data))
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Не удалось загрузить настройки')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const setField = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((prev) => (prev ? { ...prev, [key]: value } : prev))
  }

  const onSave = async () => {
    if (!form) return
    setSaving(true)
    setError(null)
    try {
      const payload: TenantIntegrationConfigUpdatePayload = {}
      if (form.telegram_bot_token && form.telegram_bot_token !== MASK) {
        payload.telegram_bot_token = form.telegram_bot_token
      }
      payload.telegram_bot_username = form.telegram_bot_username.trim().replace(/^@+/, '')
      payload.telegram_oidc_client_id = form.telegram_oidc_client_id.trim()
      payload.telegram_oidc_redirect_uri = form.telegram_oidc_redirect_uri.trim()
      if (form.telegram_oidc_client_secret && form.telegram_oidc_client_secret !== MASK) {
        payload.telegram_oidc_client_secret = form.telegram_oidc_client_secret
      }
      if (form.requests_file_gateway_token && form.requests_file_gateway_token !== MASK) {
        payload.requests_file_gateway_token = form.requests_file_gateway_token
      }
      const chatRaw = form.messaging_gateway_feedback_recipient_id.trim()
      if (chatRaw === '') {
        payload.messaging_gateway_feedback_recipient_id = null
      } else {
        const n = Number(chatRaw)
        if (!Number.isFinite(n)) {
          setError('Chat ID для фидбека должен быть числом.')
          setSaving(false)
          return
        }
        payload.messaging_gateway_feedback_recipient_id = Math.trunc(n)
      }
      payload.messaging_gateway_feedback_action = form.messaging_gateway_feedback_action.trim()

      const data = await updateTenantIntegrationConfig(payload)
      setForm(toFormState(data))
      message.success('Настройки интеграций сохранены')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Не удалось сохранить настройки')
    } finally {
      setSaving(false)
    }
  }

  const onWebhookAction = async (action: 'set' | 'info' | 'delete') => {
    setSaving(true)
    setError(null)
    try {
      await manageMessagingWebhook(action)
      await load()
      message.success(
        action === 'set'
          ? 'Webhook установлен'
          : action === 'delete'
            ? 'Webhook удален'
            : 'Статус webhook обновлен',
      )
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Не удалось выполнить операцию webhook')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Space direction="vertical" size={12} style={{ display: 'flex' }}>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Интеграционные настройки
      </Typography.Title>
      <Typography.Paragraph type="secondary">
        URL и действия messaging gateway задаются на стороне деплоя (
        <Typography.Text code>MESSAGING_GATEWAY_SEND_URL</Typography.Text>,{' '}
        <Typography.Text code>MESSAGING_GATEWAY_*_ACTION</Typography.Text>). Здесь — секреты и параметры,
        специфичные для tenant (бот, OIDC, file gateway, фидбек).
      </Typography.Paragraph>
      <Alert
        type="info"
        showIcon
        message="Подсказка по секретам"
        description="Значение ******** означает, что секрет уже сохранен. Оставьте как есть — секрет не изменится. Введите новое значение только если хотите обновить секрет."
      />
      {error ? <Alert type="error" message={error} showIcon /> : null}

      <Card loading={loading}>
        {form ? (
          <Space direction="vertical" size={12} style={{ display: 'flex' }}>
            <Typography.Text strong>Telegram и OIDC</Typography.Text>
            <Input.Password
              placeholder="Telegram bot token (OTP + Notes + карточки согласований)"
              value={form.telegram_bot_token}
              onChange={(e) => setField('telegram_bot_token', e.target.value)}
            />
            <Input
              placeholder="Telegram bot username (Login Widget)"
              value={form.telegram_bot_username}
              onChange={(e) => setField('telegram_bot_username', e.target.value)}
            />
            <Input
              placeholder="Telegram OIDC client id"
              value={form.telegram_oidc_client_id}
              onChange={(e) => setField('telegram_oidc_client_id', e.target.value)}
            />
            <Input.Password
              placeholder="Telegram OIDC client secret"
              value={form.telegram_oidc_client_secret}
              onChange={(e) => setField('telegram_oidc_client_secret', e.target.value)}
            />
            <Input
              placeholder="Telegram OIDC redirect URI"
              value={form.telegram_oidc_redirect_uri}
              onChange={(e) => setField('telegram_oidc_redirect_uri', e.target.value)}
            />

            <Divider style={{ margin: '4px 0' }} />
            <Typography.Text strong>Telegram webhook</Typography.Text>
            <Space>
              <Tag color={form.messaging_gateway_webhook_connected ? 'green' : 'red'}>
                {form.messaging_gateway_webhook_connected ? 'Подключен' : 'Не подключен'}
              </Tag>
              <Typography.Text type="secondary">{form.messaging_gateway_webhook_url || 'URL не установлен'}</Typography.Text>
            </Space>
            {form.messaging_gateway_webhook_error ? (
              <Alert type="warning" showIcon message={`Webhook error: ${form.messaging_gateway_webhook_error}`} />
            ) : null}
            <Space>
              <Button onClick={() => void onWebhookAction('set')} loading={saving}>
                setWebhook
              </Button>
              <Button onClick={() => void onWebhookAction('info')} loading={saving}>
                getWebhookInfo
              </Button>
              <Button danger onClick={() => void onWebhookAction('delete')} loading={saving}>
                deleteWebhook
              </Button>
            </Space>

            <Divider style={{ margin: '4px 0' }} />
            <Typography.Text strong>Requests file gateway</Typography.Text>
            <Typography.Text type="secondary">
              Токен для входящих запросов file gateway.
            </Typography.Text>
            <Input.Password
              placeholder="Requests file gateway token"
              value={form.requests_file_gateway_token}
              onChange={(e) => setField('requests_file_gateway_token', e.target.value)}
            />

            <Divider style={{ margin: '4px 0' }} />
            <Typography.Text strong>Обратная связь портала</Typography.Text>
            <Typography.Text type="secondary">
              Сообщения с кнопки «Обратная связь» уходят через messaging gateway.
            </Typography.Text>
            <Input
              placeholder="recipient_id получателя фидбека (число)"
              value={form.messaging_gateway_feedback_recipient_id}
              onChange={(e) => setField('messaging_gateway_feedback_recipient_id', e.target.value)}
            />
            <Input
              placeholder="Action, напр. send_portal_feedback"
              value={form.messaging_gateway_feedback_action}
              onChange={(e) => setField('messaging_gateway_feedback_action', e.target.value)}
            />

            <Space>
              <Button onClick={() => void load()} disabled={saving}>
                Обновить
              </Button>
              <Button type="primary" onClick={() => void onSave()} loading={saving}>
                Сохранить
              </Button>
            </Space>
          </Space>
        ) : null}
      </Card>
    </Space>
  )
}
