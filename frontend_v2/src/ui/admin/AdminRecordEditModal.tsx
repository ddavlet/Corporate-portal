import { useEffect, useMemo, useState } from 'react'
import { Alert, Form, Input, InputNumber, Modal, Select, Space, Switch, Typography, message } from 'antd'
import { apiFetch } from '../../lib/api'
import { planAdminEditFieldsFromRow } from '../../lib/adminModuleCrudFields'

/** Достаёт человекочитаемую ошибку из тела ответа DRF. */
export function extractApiError(json: unknown, status: number): string {
  if (json && typeof json === 'object') {
    const j = json as Record<string, unknown>
    if (typeof j.detail === 'string') return j.detail
    if (typeof j.message === 'string') return j.message
    if (typeof j.error === 'string') return j.error
  }
  return `Ошибка сервера (${status})`
}

type AnyRecord = Record<string, unknown> & { id?: number | string }

type Props = {
  /** Эндпоинт коллекции, напр. `/api/requests/`. PATCH уходит на `${endpoint}${id}/`. */
  endpoint: string
  record: AnyRecord | null
  open: boolean
  onClose: () => void
  /** Вызывается после успешного сохранения (обычно перезагрузка списка). */
  onSaved: () => void
  title?: string
}

/**
 * Универсальная модалка правки записи: динамические поля из строки → PATCH.
 * Та же форма, что в Админке (раздел «Данные модулей»), вынесена для
 * переиспользования прямо в списках портала.
 */
export function AdminRecordEditModal({ endpoint, record, open, onClose, onSaved, title }: Props) {
  const [form] = Form.useForm<Record<string, unknown>>()
  const [saving, setSaving] = useState(false)

  const plan = useMemo(() => (record ? planAdminEditFieldsFromRow(record) : null), [record])

  useEffect(() => {
    if (open && plan) {
      form.resetFields()
      form.setFieldsValue(plan.initial as Parameters<typeof form.setFieldsValue>[0])
    }
  }, [open, plan, form])

  const handleSave = async () => {
    if (!record) return
    const id = record.id
    if (id === undefined || id === null || id === '') {
      message.error('У записи отсутствует id')
      return
    }
    const payload = (await form.validateFields()) as Record<string, unknown>
    setSaving(true)
    try {
      const res = await apiFetch(`${endpoint}${id}/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const json = await res.json().catch(() => null)
      if (!res.ok) throw new Error(extractApiError(json, res.status))
      message.success('Сохранено')
      onSaved()
      onClose()
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Не удалось сохранить')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open={open}
      title={title ?? 'Редактировать запись'}
      okText="Сохранить"
      onOk={() => void handleSave()}
      confirmLoading={saving}
      onCancel={onClose}
      width={920}
    >
      <Form form={form} layout="vertical">
        {(plan?.fields ?? []).map(({ key, type, choices }) => {
          if (choices?.length) {
            return (
              <Form.Item key={key} label={key} name={key}>
                <Select
                  allowClear
                  showSearch
                  optionFilterProp="label"
                  options={choices.map((c) => ({ value: c.value, label: c.label }))}
                  placeholder={`Выберите ${key}`}
                />
              </Form.Item>
            )
          }
          if (type === 'boolean') {
            return (
              <Form.Item key={key} label={key} name={key} valuePropName="checked">
                <Switch />
              </Form.Item>
            )
          }
          if (type === 'number') {
            return (
              <Form.Item key={key} label={key} name={key}>
                <InputNumber style={{ width: '100%' }} />
              </Form.Item>
            )
          }
          return (
            <Form.Item key={key} label={key} name={key}>
              <Input allowClear />
            </Form.Item>
          )
        })}
      </Form>
      {plan?.nonEditable.length ? (
        <Alert
          type="info"
          showIcon
          message="Часть полей недоступна для редактирования в упрощенной форме"
          description={
            <Space direction="vertical">
              {plan.nonEditable.map((f) => (
                <Typography.Text key={f.key} type="secondary">
                  {f.key}: {JSON.stringify(f.value)}
                </Typography.Text>
              ))}
            </Space>
          }
        />
      ) : null}
    </Modal>
  )
}
