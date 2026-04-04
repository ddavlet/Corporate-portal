import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Divider, Input, Space, Typography, message } from 'antd'
import {
  getTenantIntegrationConfig,
  type TenantIntegrationConfigResponse,
  updateTenantIntegrationConfig,
} from '../../lib/api'

type FormState = {
  telegram_bot_token: string
  telegram_approvals_bridge_dispatch_url: string
  telegram_approvals_send_action: string
  telegram_approvals_edit_action: string
  telegram_approvals_draft_notification_action: string
  telegram_approvals_message_template: string
  telegram_approvals_header_new_template: string
  telegram_approvals_header_step_approved_template: string
  telegram_approvals_header_fully_approved_template: string
  telegram_approvals_header_closed_template: string
  telegram_approvals_header_rejected_template: string
  telegram_approvals_subheader_payment_responsible_template: string
  telegram_approvals_subheader_rejected_by_template: string
  telegram_approvals_bridge_token: string
  n8n_integration_token: string
  requests_file_gateway_token: string
}

const MASK = '********'

function isAbsoluteUrl(v: string): boolean {
  const s = v.trim()
  return s.startsWith('http://') || s.startsWith('https://')
}

function toFormState(data: TenantIntegrationConfigResponse): FormState {
  return {
    telegram_bot_token: data.telegram_bot_token || '',
    telegram_approvals_bridge_dispatch_url: data.telegram_approvals_bridge_dispatch_url || '',
    telegram_approvals_send_action: data.telegram_approvals_send_action || '',
    telegram_approvals_edit_action: data.telegram_approvals_edit_action || '',
    telegram_approvals_draft_notification_action: data.telegram_approvals_draft_notification_action || '',
    telegram_approvals_message_template: data.telegram_approvals_message_template || '',
    telegram_approvals_header_new_template: data.telegram_approvals_header_new_template || '',
    telegram_approvals_header_step_approved_template: data.telegram_approvals_header_step_approved_template || '',
    telegram_approvals_header_fully_approved_template: data.telegram_approvals_header_fully_approved_template || '',
    telegram_approvals_header_closed_template: data.telegram_approvals_header_closed_template || '',
    telegram_approvals_header_rejected_template: data.telegram_approvals_header_rejected_template || '',
    telegram_approvals_subheader_payment_responsible_template:
      data.telegram_approvals_subheader_payment_responsible_template || '',
    telegram_approvals_subheader_rejected_by_template: data.telegram_approvals_subheader_rejected_by_template || '',
    telegram_approvals_bridge_token: data.telegram_approvals_bridge_token || '',
    n8n_integration_token: data.n8n_integration_token || '',
    requests_file_gateway_token: data.requests_file_gateway_token || '',
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

  const validationError = useMemo(() => {
    if (!form) return null
    if (form.telegram_approvals_bridge_dispatch_url && !isAbsoluteUrl(form.telegram_approvals_bridge_dispatch_url)) {
      return 'Поле Dispatch URL должно быть абсолютным URL.'
    }
    return null
  }, [form])

  const setField = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((prev) => (prev ? { ...prev, [key]: value } : prev))
  }

  const onSave = async () => {
    if (!form || validationError) return
    setSaving(true)
    setError(null)
    try {
      const payload: Record<string, string> = {
        telegram_approvals_bridge_dispatch_url: form.telegram_approvals_bridge_dispatch_url.trim(),
        telegram_approvals_send_action: form.telegram_approvals_send_action.trim(),
        telegram_approvals_edit_action: form.telegram_approvals_edit_action.trim(),
        telegram_approvals_draft_notification_action: form.telegram_approvals_draft_notification_action.trim(),
        telegram_approvals_message_template: form.telegram_approvals_message_template,
        telegram_approvals_header_new_template: form.telegram_approvals_header_new_template,
        telegram_approvals_header_step_approved_template: form.telegram_approvals_header_step_approved_template,
        telegram_approvals_header_fully_approved_template: form.telegram_approvals_header_fully_approved_template,
        telegram_approvals_header_closed_template: form.telegram_approvals_header_closed_template,
        telegram_approvals_header_rejected_template: form.telegram_approvals_header_rejected_template,
        telegram_approvals_subheader_payment_responsible_template:
          form.telegram_approvals_subheader_payment_responsible_template,
        telegram_approvals_subheader_rejected_by_template: form.telegram_approvals_subheader_rejected_by_template,
      }
      // Send secrets only when user entered a new value.
      if (form.telegram_bot_token && form.telegram_bot_token !== MASK) {
        payload.telegram_bot_token = form.telegram_bot_token
      }
      if (form.telegram_approvals_bridge_token && form.telegram_approvals_bridge_token !== MASK) {
        payload.telegram_approvals_bridge_token = form.telegram_approvals_bridge_token
      }
      if (form.n8n_integration_token && form.n8n_integration_token !== MASK) {
        payload.n8n_integration_token = form.n8n_integration_token
      }
      if (form.requests_file_gateway_token && form.requests_file_gateway_token !== MASK) {
        payload.requests_file_gateway_token = form.requests_file_gateway_token
      }

      const data = await updateTenantIntegrationConfig(payload)
      setForm(toFormState(data))
      message.success('Настройки интеграций сохранены')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Не удалось сохранить настройки')
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
        Tenant-специфичные URL, actions и секреты для telegram approvals и n8n/file gateway.
      </Typography.Paragraph>
      <Alert
        type="info"
        showIcon
        message="Подсказка по секретам"
        description="Значение ******** означает, что секрет уже сохранен. Оставьте как есть — секрет не изменится. Введите новое значение только если хотите обновить секрет. Для входящих запросов в backend используйте единый N8N_INTEGRATION_TOKEN."
      />
      {error ? <Alert type="error" message={error} showIcon /> : null}
      {validationError ? <Alert type="warning" message={validationError} showIcon /> : null}

      <Card loading={loading}>
        {form ? (
          <Space direction="vertical" size={12} style={{ display: 'flex' }}>
            <Typography.Text strong>Telegram approvals</Typography.Text>
            <Typography.Text type="secondary">
              Dispatch URL должен быть абсолютным (http/https). Action-поля обычно менять не нужно, если backend и bridge уже синхронизированы.
            </Typography.Text>
            <Input.Password
              placeholder="Telegram bot token (OTP + Notes)"
              value={form.telegram_bot_token}
              onChange={(e) => setField('telegram_bot_token', e.target.value)}
            />
            <Input
              placeholder="Bridge dispatch URL"
              value={form.telegram_approvals_bridge_dispatch_url}
              onChange={(e) => setField('telegram_approvals_bridge_dispatch_url', e.target.value)}
            />
            <Input
              placeholder="Send action"
              value={form.telegram_approvals_send_action}
              onChange={(e) => setField('telegram_approvals_send_action', e.target.value)}
            />
            <Input
              placeholder="Edit action"
              value={form.telegram_approvals_edit_action}
              onChange={(e) => setField('telegram_approvals_edit_action', e.target.value)}
            />
            <Input
              placeholder="Draft notification action (n8n), напр. send_draft_notification"
              value={form.telegram_approvals_draft_notification_action}
              onChange={(e) => setField('telegram_approvals_draft_notification_action', e.target.value)}
            />
            <Input.TextArea
              placeholder="Telegram message template (HTML)"
              value={form.telegram_approvals_message_template}
              onChange={(e) => setField('telegram_approvals_message_template', e.target.value)}
              autoSize={{ minRows: 10, maxRows: 18 }}
            />
            <Typography.Text type="secondary">
              Доступные переменные: {'{header}'}, {'{subheader}'}, {'{subheader_block}'}, {'{company_payer}'}, {'{project_title}'}, {'{vendor}'}, {'{category}'}, {'{amount}'}, {'{currency}'}, {'{payment_type}'}, {'{payment_purpose}'}, {'{description}'}, {'{accrual_month}'}, {'{urgency}'}, {'{requester}'}, {'{submitted_at}'}.
            </Typography.Text>
            <Input placeholder="Header: new" value={form.telegram_approvals_header_new_template} onChange={(e) => setField('telegram_approvals_header_new_template', e.target.value)} />
            <Input placeholder="Header: step approved" value={form.telegram_approvals_header_step_approved_template} onChange={(e) => setField('telegram_approvals_header_step_approved_template', e.target.value)} />
            <Input placeholder="Header: fully approved" value={form.telegram_approvals_header_fully_approved_template} onChange={(e) => setField('telegram_approvals_header_fully_approved_template', e.target.value)} />
            <Input placeholder="Header: closed" value={form.telegram_approvals_header_closed_template} onChange={(e) => setField('telegram_approvals_header_closed_template', e.target.value)} />
            <Input placeholder="Header: rejected" value={form.telegram_approvals_header_rejected_template} onChange={(e) => setField('telegram_approvals_header_rejected_template', e.target.value)} />
            <Input placeholder="Subheader: payment responsible" value={form.telegram_approvals_subheader_payment_responsible_template} onChange={(e) => setField('telegram_approvals_subheader_payment_responsible_template', e.target.value)} />
            <Input placeholder="Subheader: rejected by" value={form.telegram_approvals_subheader_rejected_by_template} onChange={(e) => setField('telegram_approvals_subheader_rejected_by_template', e.target.value)} />
            <Typography.Text type="secondary">
              Переменные для шапок: {'{request_id}'}, {'{payment_responsible}'}, {'{rejected_by}'}.
            </Typography.Text>
            <Input.Password
              placeholder="Bridge token"
              value={form.telegram_approvals_bridge_token}
              onChange={(e) => setField('telegram_approvals_bridge_token', e.target.value)}
            />

            <Divider style={{ margin: '4px 0' }} />
            <Typography.Text strong>n8n / requests gateway</Typography.Text>
            <Typography.Text type="secondary">
              N8N integration token используется для входящих запросов в backend (включая callback webhook). Меняйте только при ротации ключей.
            </Typography.Text>
            <Input.Password
              placeholder="N8N integration token"
              value={form.n8n_integration_token}
              onChange={(e) => setField('n8n_integration_token', e.target.value)}
            />
            <Input.Password
              placeholder="Requests file gateway token"
              value={form.requests_file_gateway_token}
              onChange={(e) => setField('requests_file_gateway_token', e.target.value)}
            />

            <Space>
              <Button onClick={() => void load()} disabled={saving}>
                Обновить
              </Button>
              <Button type="primary" onClick={() => void onSave()} loading={saving} disabled={!!validationError}>
                Сохранить
              </Button>
            </Space>
          </Space>
        ) : null}
      </Card>
    </Space>
  )
}

