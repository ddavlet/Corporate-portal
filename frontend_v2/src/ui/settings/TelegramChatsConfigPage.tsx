import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Form,
  Input,
  Modal,
  Space,
  Switch,
  Table,
  Typography,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  createTelegramChat,
  deleteTelegramChat,
  listTelegramChats,
  patchTelegramChat,
  type TenantTelegramChatDto,
} from '../../lib/api'

export function TelegramChatsConfigPage() {
  const [loading, setLoading] = useState(true)
  const [rows, setRows] = useState<TenantTelegramChatDto[]>([])
  const [error, setError] = useState<string | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<TenantTelegramChatDto | null>(null)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setRows(await listTelegramChats())
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    form.setFieldsValue({ is_active: true })
    setModalOpen(true)
  }

  const openEdit = (r: TenantTelegramChatDto) => {
    setEditing(r)
    form.setFieldsValue({ name: r.name, chat_id: r.chat_id, is_active: r.is_active })
    setModalOpen(true)
  }

  const submitModal = async () => {
    try {
      const v = await form.validateFields()
      if (editing) {
        await patchTelegramChat(editing.id, { name: v.name, is_active: v.is_active })
        message.success('Сохранено')
      } else {
        await createTelegramChat({ name: v.name, chat_id: v.chat_id, is_active: v.is_active })
        message.success('Telegram-группа добавлена')
      }
      setModalOpen(false)
      void load()
    } catch (e: unknown) {
      if (e && typeof e === 'object' && 'errorFields' in e) return
      message.error(e instanceof Error ? e.message : 'Ошибка')
    }
  }

  const columns: ColumnsType<TenantTelegramChatDto> = [
    { title: 'Название', dataIndex: 'name' },
    { title: 'Chat ID', dataIndex: 'chat_id' },
    {
      title: 'Активна',
      dataIndex: 'is_active',
      width: 100,
      render: (v: boolean, r) => (
        <Switch
          checked={v}
          onChange={async (checked) => {
            try {
              await patchTelegramChat(r.id, { is_active: checked })
              void load()
            } catch (e: unknown) {
              message.error(e instanceof Error ? e.message : 'Ошибка')
            }
          }}
        />
      ),
    },
    {
      title: '',
      key: 'actions',
      width: 180,
      render: (_, r) => (
        <Space>
          <Button size="small" onClick={() => openEdit(r)}>
            Изменить
          </Button>
          <Button
            size="small"
            danger
            onClick={() => {
              Modal.confirm({
                title: 'Удалить Telegram-группу?',
                content: 'Конфигурации согласований, ссылающиеся на этот чат, потеряют привязку.',
                onOk: async () => {
                  try {
                    await deleteTelegramChat(r.id)
                    message.success('Удалено')
                    void load()
                  } catch (e: unknown) {
                    message.error(e instanceof Error ? e.message : 'Ошибка')
                  }
                },
              })
            }}
          >
            Удалить
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ maxWidth: 900 }}>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Telegram-группы
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
        Справочник групп и каналов Telegram, которые используются в конфигурациях согласований и уведомлений. Chat ID
        можно узнать через бота @userinfobot или похожие инструменты (обычно большое отрицательное число для групп,
        например −1001234567890).
      </Typography.Paragraph>
      <Button type="primary" onClick={openCreate} style={{ marginBottom: 16 }}>
        Добавить группу
      </Button>
      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} /> : null}
      <Table<TenantTelegramChatDto>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={rows}
        pagination={false}
      />

      <Modal
        title={editing ? 'Telegram-группа' : 'Новая Telegram-группа'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => void submitModal()}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="Название" rules={[{ required: true, message: 'Введите название' }]}>
            <Input placeholder="Например: Группа согласований" maxLength={100} />
          </Form.Item>
          <Form.Item
            name="chat_id"
            label="Chat ID"
            rules={[{ required: true, message: 'Введите Chat ID' }]}
            extra="Telegram ID группы или канала (число, может быть отрицательным)"
          >
            <Input placeholder="-1001234567890" disabled={!!editing} />
          </Form.Item>
          <Form.Item name="is_active" label="Активна" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
