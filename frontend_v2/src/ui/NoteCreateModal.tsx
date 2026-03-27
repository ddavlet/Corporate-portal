import { Alert, Button, Form, Input, Modal, Select, Space, Typography, message } from 'antd'
import { useEffect, useState } from 'react'
import { apiFetch } from '../lib/api'

type RecipientOption = {
  id: number
  full_name: string
  username: string
  telegram_chat_id: number
}

type NoteCreateModalProps = {
  open: boolean
  onCancel: () => void
  targetType: 'request' | 'cash' | 'bank'
  targetId: number | null
}

export function NoteCreateModal({ open, onCancel, targetType, targetId }: NoteCreateModalProps) {
  const [form] = Form.useForm()
  const [loadingRecipients, setLoadingRecipients] = useState(false)
  const [saving, setSaving] = useState(false)
  const [recipients, setRecipients] = useState<RecipientOption[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    let cancelled = false
    ;(async () => {
      setLoadingRecipients(true)
      setError(null)
      try {
        const res = await apiFetch('/api/notes/recipients/')
        const json = (await res.json().catch(() => null)) as { items?: RecipientOption[] } | null
        if (!res.ok) {
          throw new Error(typeof json === 'object' && json ? JSON.stringify(json) : `HTTP ${res.status}`)
        }
        if (!cancelled) setRecipients(Array.isArray(json?.items) ? json!.items : [])
      } catch (e: any) {
        if (!cancelled) setError(e?.message || 'Не удалось загрузить получателей')
      } finally {
        if (!cancelled) setLoadingRecipients(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [open])

  const handleSubmit = async () => {
    if (!targetId) {
      setError('Целевая запись не определена.')
      return
    }
    try {
      const values = await form.validateFields()
      setSaving(true)
      setError(null)
      const res = await apiFetch('/api/notes/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          recipient_user: values.recipient_user,
          message: values.message,
          target_type: targetType,
          target_id: targetId,
        }),
      })
      const json = (await res.json().catch(() => null)) as
        | { delivery?: { status?: string; error?: string | null } }
        | null
      if (!res.ok) {
        throw new Error(typeof json === 'object' && json ? JSON.stringify(json) : `HTTP ${res.status}`)
      }

      const status = json?.delivery?.status
      if (status === 'failed') {
        message.warning(json?.delivery?.error || 'Заметка сохранена, но Telegram отправка не удалась.')
      } else {
        message.success('Заметка отправлена.')
      }
      form.resetFields()
      onCancel()
    } catch (e: any) {
      setError(e?.message || 'Не удалось создать заметку')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open={open}
      title="Добавить заметку"
      onCancel={onCancel}
      footer={
        <Space>
          <Button onClick={onCancel}>Отмена</Button>
          <Button type="primary" loading={saving} onClick={handleSubmit}>
            Отправить
          </Button>
        </Space>
      }
    >
      <Space direction="vertical" size={10} style={{ display: 'flex' }}>
        <Typography.Text type="secondary">
          Выберите получателя и отправьте заметку в Telegram с ссылкой на полную страницу записи.
        </Typography.Text>
        {error ? <Alert type="error" showIcon message={error} /> : null}
        <Form form={form} layout="vertical">
          <Form.Item name="recipient_user" label="Кому" rules={[{ required: true, message: 'Выберите получателя.' }]}>
            <Select
              showSearch
              loading={loadingRecipients}
              placeholder="Выберите пользователя"
              optionFilterProp="label"
              options={recipients.map((item) => ({
                value: item.id,
                label: `${item.full_name || item.username} (${item.username})`,
              }))}
            />
          </Form.Item>
          <Form.Item name="message" label="Текст заметки" rules={[{ required: true, message: 'Введите текст.' }]}>
            <Input.TextArea rows={5} maxLength={2000} showCount />
          </Form.Item>
        </Form>
      </Space>
    </Modal>
  )
}
