import { useEffect, useState } from 'react'
import { Alert, Button, Form, Input, Skeleton, Space, Typography, message } from 'antd'
import { getTasksConfig, patchTasksConfig } from '../../lib/tasksApi'

interface FormValues {
  tasks_webapp_url: string
}

export function TasksConfigPage() {
  const [form] = Form.useForm<FormValues>()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const cfg = await getTasksConfig()
        if (!cancelled) form.setFieldsValue({ tasks_webapp_url: cfg.tasks_webapp_url })
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Ошибка загрузки')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [form])

  const handleSave = async () => {
    let values: FormValues
    try {
      values = await form.validateFields()
    } catch {
      return
    }
    setSaving(true)
    setError(null)
    try {
      await patchTasksConfig({ tasks_webapp_url: values.tasks_webapp_url.trim() })
      void message.success('Настройки задач сохранены')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось сохранить')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <Skeleton active paragraph={{ rows: 3 }} />

  return (
    <div style={{ maxWidth: 600 }}>
      <Typography.Title level={4} style={{ marginBottom: 4 }}>
        Задачи — Telegram уведомления
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 20 }}>
        Ежедневный дайджест отправляется пользователям в 09:00 по Ташкенту. Укажите URL
        Telegram WebApp, чтобы добавить кнопку «Открыть задачи» в сообщение. Оставьте поле
        пустым, чтобы кнопку не показывать.
      </Typography.Paragraph>

      {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />}

      <Form form={form} layout="vertical">
        <Form.Item
          name="tasks_webapp_url"
          label="URL Telegram WebApp для задач"
          extra="Например: https://t.me/mybot/tasks"
        >
          <Input
            placeholder="https://t.me/..."
            allowClear
            maxLength={500}
          />
        </Form.Item>

        <Form.Item style={{ marginBottom: 0 }}>
          <Space>
            <Button type="primary" loading={saving} onClick={() => void handleSave()}>
              Сохранить
            </Button>
          </Space>
        </Form.Item>
      </Form>
    </div>
  )
}
