import { useState } from 'react'
import { Button, Empty, Form, Input, Modal, Skeleton, Space, Switch, Table, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'

import { createInvestCompany, type InvestCompanyRow } from '../../lib/api'

type Props = {
  loading: boolean
  companies: InvestCompanyRow[]
  onCreated: () => Promise<void> | void
}

export function CompaniesTab({ loading, companies, onCreated }: Props) {
  const [form] = Form.useForm<{ name: string; comment?: string; is_active: boolean }>()
  const [open, setOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const columns: ColumnsType<InvestCompanyRow> = [
    { title: 'ID', dataIndex: 'id', width: 80, sorter: (a, b) => a.id - b.id },
    { title: 'Компания', dataIndex: 'name', sorter: (a, b) => a.name.localeCompare(b.name) },
    { title: 'Комментарий', dataIndex: 'comment', render: (v: string) => v || '-' },
    {
      title: 'Активна',
      dataIndex: 'is_active',
      width: 110,
      render: (v: boolean) => (v ? 'Да' : 'Нет'),
      sorter: (a, b) => Number(a.is_active) - Number(b.is_active),
    },
  ]

  const openCreate = () => {
    form.resetFields()
    form.setFieldsValue({ is_active: true })
    setOpen(true)
  }

  const submit = async () => {
    let values: { name: string; comment?: string; is_active: boolean }
    try {
      values = await form.validateFields()
    } catch {
      return
    }
    setSubmitting(true)
    try {
      await createInvestCompany({
        name: values.name.trim(),
        comment: values.comment ?? '',
        is_active: values.is_active,
      })
      message.success('Компания создана')
      setOpen(false)
      await onCreated()
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Не удалось создать компанию')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Space style={{ width: '100%', justifyContent: 'space-between' }} wrap>
        <Typography.Text type="secondary">Всего компаний: {companies.length}</Typography.Text>
        <Button type="primary" onClick={openCreate}>
          Создать компанию
        </Button>
      </Space>

      {loading ? (
        <Skeleton active />
      ) : (
        <Table
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={companies}
          pagination={{ pageSize: 20 }}
          locale={{
            emptyText: (
              <Empty
                description="Компаний пока нет"
                image={Empty.PRESENTED_IMAGE_SIMPLE}
              >
                <Button type="primary" onClick={openCreate}>
                  Создать первую компанию
                </Button>
              </Empty>
            ),
          }}
        />
      )}

      <Modal
        open={open}
        title="Создать компанию"
        okText="Создать"
        cancelText="Отмена"
        confirmLoading={submitting}
        onOk={submit}
        onCancel={() => setOpen(false)}
        destroyOnClose
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item
            label="Название"
            name="name"
            rules={[
              { required: true, message: 'Укажите название' },
              { max: 255, message: 'Не более 255 символов' },
            ]}
          >
            <Input maxLength={255} autoFocus />
          </Form.Item>
          <Form.Item label="Комментарий" name="comment">
            <Input.TextArea rows={3} maxLength={1000} />
          </Form.Item>
          <Form.Item label="Активна" name="is_active" valuePropName="checked" initialValue={true}>
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  )
}
