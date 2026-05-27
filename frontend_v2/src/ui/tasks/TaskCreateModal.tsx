import { useEffect, useState } from 'react'
import { Alert, Button, Form, Input, Modal, Select, Space, message } from 'antd'
import { createTask, listAssigneeCandidates } from '../../lib/tasksApi'
import type { AssigneeCandidate } from '../../lib/tasksApi'

interface FormValues {
  title: string
  description?: string
  assignee_id: number
}

interface Props {
  onClose: (created: boolean) => void
}

export function TaskCreateModal({ onClose }: Props) {
  const [form] = Form.useForm<FormValues>()
  const [candidates, setCandidates] = useState<AssigneeCandidate[]>([])
  const [loadingCandidates, setLoadingCandidates] = useState(true)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const data = await listAssigneeCandidates()
        if (!cancelled) {
          setCandidates(data)
          if (data.length === 1) {
            form.setFieldValue('assignee_id', data[0].id)
          }
        }
      } finally {
        if (!cancelled) setLoadingCandidates(false)
      }
    })()
    return () => { cancelled = true }
  }, [form])

  const handleSubmit = async () => {
    let values: FormValues
    try {
      values = await form.validateFields()
    } catch {
      return
    }

    setSaving(true)
    try {
      await createTask({
        title: values.title.trim(),
        description: values.description?.trim() ?? '',
        assignee_id: values.assignee_id,
      })
      void message.success('Задача создана')
      onClose(true)
    } catch (err) {
      void message.error(err instanceof Error ? err.message : 'Не удалось создать задачу')
    } finally {
      setSaving(false)
    }
  }

  const isSingleCandidate = candidates.length === 1
  const noCandidates = !loadingCandidates && candidates.length === 0

  return (
    <Modal
      open
      title="Новая задача"
      onCancel={() => onClose(false)}
      destroyOnHidden
      footer={
        <Space>
          <Button onClick={() => onClose(false)}>Отмена</Button>
          <Button
            type="primary"
            loading={saving}
            disabled={noCandidates}
            onClick={() => void handleSubmit()}
          >
            Создать
          </Button>
        </Space>
      }
    >
      {noCandidates && (
        <Alert
          type="warning"
          showIcon
          message="Нет доступных исполнителей"
          description="В этой компании нет активных пользователей, которым можно назначить задачу."
          style={{ marginBottom: 12 }}
        />
      )}
      <Form form={form} layout="vertical" style={{ marginTop: 8 }}>
        <Form.Item
          name="title"
          label="Название"
          rules={[{ required: true, message: 'Введите название задачи' }]}
        >
          <Input maxLength={255} placeholder="Кратко опишите задачу" />
        </Form.Item>

        <Form.Item name="description" label="Описание">
          <Input.TextArea
            rows={3}
            maxLength={4000}
            showCount
            placeholder="Подробности (необязательно)"
          />
        </Form.Item>

        {!isSingleCandidate && (
          <Form.Item
            name="assignee_id"
            label="Исполнитель"
            rules={[{ required: true, message: 'Выберите исполнителя' }]}
          >
            <Select
              showSearch
              loading={loadingCandidates}
              placeholder="Выберите пользователя"
              optionFilterProp="label"
              options={candidates.map((c) => ({ value: c.id, label: c.username }))}
            />
          </Form.Item>
        )}

        {isSingleCandidate && (
          <Form.Item name="assignee_id" hidden>
            <Input />
          </Form.Item>
        )}
      </Form>
    </Modal>
  )
}
