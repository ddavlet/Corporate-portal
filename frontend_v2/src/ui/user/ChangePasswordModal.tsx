import { useState } from 'react'
import { Alert, Form, Input, Modal, Typography, message } from 'antd'
import { changePassword } from '../../lib/api'

type Props = {
  open: boolean
  onClose: () => void
}

type FormValues = {
  current?: string
  next: string
  confirm: string
}

export function ChangePasswordModal({ open, onClose }: Props) {
  const [form] = Form.useForm<FormValues>()
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleClose = () => {
    form.resetFields()
    setError(null)
    onClose()
  }

  const onFinish = async (values: FormValues) => {
    setError(null)
    setSubmitting(true)
    try {
      const current = values.current?.trim() ?? ''
      await changePassword({
        ...(current ? { old_password: current } : {}),
        new_password: values.next,
      })
      message.success('Пароль обновлён.')
      handleClose()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Не удалось сменить пароль')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      title="Сменить пароль"
      open={open}
      onCancel={handleClose}
      okText="Сохранить"
      cancelText="Отмена"
      confirmLoading={submitting}
      destroyOnClose
      onOk={() => form.submit()}
    >
      <Form
        form={form}
        layout="vertical"
        onFinish={onFinish}
        style={{ marginTop: 8 }}
        requiredMark={false}
      >
        {error ? (
          <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />
        ) : null}
        <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
          Если вы входите по коду из письма и пароль не задавался, оставьте поле «Текущий пароль» пустым.
        </Typography.Paragraph>
        <Form.Item name="current" label="Текущий пароль">
          <Input.Password autoComplete="current-password" />
        </Form.Item>
        <Form.Item
          name="next"
          label="Новый пароль"
          rules={[{ required: true, message: 'Введите новый пароль' }]}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Form.Item
          name="confirm"
          label="Повторите новый пароль"
          dependencies={['next']}
          rules={[
            { required: true, message: 'Подтвердите пароль' },
            ({ getFieldValue }) => ({
              validator(_, value) {
                if (!value || getFieldValue('next') === value) {
                  return Promise.resolve()
                }
                return Promise.reject(new Error('Пароли не совпадают'))
              },
            }),
          ]}
        >
          <Input.Password autoComplete="new-password" />
        </Form.Item>
      </Form>
    </Modal>
  )
}
