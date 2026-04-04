import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  message,
  Space,
  Switch,
  Table,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  createCashRegister,
  deleteCashRegister,
  getCashRegisters,
  patchCashRegister,
  patchWallet,
  type CashRegisterDto,
} from '../../lib/api'

export function CashRegistersSettingsPage() {
  const [loading, setLoading] = useState(true)
  const [rows, setRows] = useState<CashRegisterDto[]>([])
  const [error, setError] = useState<string | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<CashRegisterDto | null>(null)
  const [openingModalFor, setOpeningModalFor] = useState<CashRegisterDto | null>(null)
  const [form] = Form.useForm()
  const [openingForm] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getCashRegisters()
      setRows(data)
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
    form.setFieldsValue({ is_active: true, sort_order: 0, is_default_for_currency: true })
    setModalOpen(true)
  }

  const openEdit = (r: CashRegisterDto) => {
    setEditing(r)
    form.setFieldsValue({
      currency: r.currency,
      name: r.name,
      code: r.code,
      description: r.description,
      is_active: r.is_active,
      sort_order: r.sort_order,
      is_default_for_currency: r.is_default_for_currency,
    })
    setModalOpen(true)
  }

  const submitModal = async () => {
    try {
      const v = await form.validateFields()
      if (editing) {
        await patchCashRegister(editing.id, {
          name: v.name,
          code: v.code,
          description: v.description,
          is_active: v.is_active,
          sort_order: v.sort_order,
          is_default_for_currency: v.is_default_for_currency,
        })
        message.success('Сохранено')
      } else {
        await createCashRegister({
          currency: v.currency,
          name: v.name,
          code: v.code,
          description: v.description,
          is_active: v.is_active,
          sort_order: v.sort_order,
          is_default_for_currency: v.is_default_for_currency,
        })
        message.success('Касса создана')
      }
      setModalOpen(false)
      void load()
    } catch (e: unknown) {
      if (e && typeof e === 'object' && 'errorFields' in e) return
      message.error(e instanceof Error ? e.message : 'Ошибка')
    }
  }

  const submitOpening = async () => {
    if (!openingModalFor) return
    try {
      const v = await openingForm.validateFields()
      await patchWallet(openingModalFor.wallet_id, { opening_balance: String(v.opening_balance) })
      message.success('Остаток на 1 янв обновлён')
      setOpeningModalFor(null)
      openingForm.resetFields()
    } catch (e: unknown) {
      if (e && typeof e === 'object' && 'errorFields' in e) return
      message.error(e instanceof Error ? e.message : 'Ошибка')
    }
  }

  const columns: ColumnsType<CashRegisterDto> = [
    { title: 'Название', dataIndex: 'name', render: (v, r) => (v || '').trim() || r.currency },
    { title: 'Код', dataIndex: 'code' },
    { title: 'Валюта', dataIndex: 'currency', width: 90 },
    {
      title: 'Активна',
      dataIndex: 'is_active',
      width: 100,
      render: (v: boolean, r) => (
        <Switch
          checked={v}
          onChange={async (checked) => {
            try {
              await patchCashRegister(r.id, { is_active: checked })
              void load()
            } catch (e: unknown) {
              message.error(e instanceof Error ? e.message : 'Ошибка')
            }
          }}
        />
      ),
    },
    { title: 'Порядок', dataIndex: 'sort_order', width: 90 },
    {
      title: '',
      key: 'actions',
      width: 220,
      render: (_, r) => (
        <Space>
          <Button size="small" onClick={() => openEdit(r)}>
            Изменить
          </Button>
          <Button size="small" onClick={() => setOpeningModalFor(r)}>
            Остаток 1 янв
          </Button>
          <Button
            size="small"
            danger
            onClick={() => {
              Modal.confirm({
                title: 'Удалить кассу?',
                onOk: async () => {
                  try {
                    await deleteCashRegister(r.id)
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
    <div style={{ maxWidth: 1100 }}>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Кассы
      </Typography.Title>
      <Typography.Paragraph type="secondary">
        Одна касса на валюту. Для остатка на начало года используйте кошелёк (поле opening_balance).
      </Typography.Paragraph>
      <Button type="primary" onClick={openCreate} style={{ marginBottom: 16 }}>
        Добавить кассу
      </Button>
      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} /> : null}
      <Table<CashRegisterDto>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={rows}
        pagination={false}
      />

      <Modal
        title={editing ? 'Касса' : 'Новая касса'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => void submitModal()}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="currency"
            label="Валюта"
            rules={[{ required: true, message: 'Укажите валюту' }]}
          >
            <Input disabled={!!editing} maxLength={10} />
          </Form.Item>
          <Form.Item name="name" label="Название">
            <Input />
          </Form.Item>
          <Form.Item name="code" label="Код">
            <Input />
          </Form.Item>
          <Form.Item name="description" label="Описание">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item name="sort_order" label="Порядок сортировки">
            <InputNumber style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="is_active" label="Активна" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item name="is_default_for_currency" label="По умолчанию для валюты" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="Остаток на 1 января (кошелёк)"
        open={!!openingModalFor}
        onCancel={() => {
          setOpeningModalFor(null)
          openingForm.resetFields()
        }}
        onOk={() => void submitOpening()}
        destroyOnClose
      >
        {openingModalFor ? (
          <Form
            form={openingForm}
            layout="vertical"
            initialValues={{ opening_balance: '' }}
          >
            <Typography.Text type="secondary">
              Кошелёк #{openingModalFor.wallet_id}, валюта {openingModalFor.currency}
            </Typography.Text>
            <Form.Item
              name="opening_balance"
              label="Остаток"
              rules={[{ required: true, message: 'Введите сумму' }]}
            >
              <Input />
            </Form.Item>
          </Form>
        ) : null}
      </Modal>
    </div>
  )
}
