import { useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Progress,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { PlusOutlined, EditOutlined, DeleteOutlined, UnorderedListOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import 'dayjs/locale/ru'
import {
  getBudgets,
  getBudgetCategories,
  createBudget,
  updateBudget,
  deleteBudget,
  getBudgetSpendDetail,
  type Budget,
  type BudgetCategory,
  type BudgetCreatePayload,
  type BudgetPeriodType,
  type BudgetSpendDetailItem,
} from '../lib/api'

dayjs.locale('ru')

const { Title, Text } = Typography

const PERIOD_LABELS: Record<BudgetPeriodType, string> = {
  monthly: 'Ежемесячно',
  quarterly: 'Ежеквартально',
  yearly: 'Ежегодно',
}

const CURRENCIES = ['UZS', 'USD', 'EUR', 'RUB']

function utilizationColor(pct: number): string {
  if (pct >= 100) return '#ff4d4f'
  if (pct >= 80) return '#faad14'
  return '#52c41a'
}

function monthOptions(year: number) {
  return Array.from({ length: 12 }, (_, i) => ({
    label: dayjs(`${year}-${String(i + 1).padStart(2, '0')}-01`).format('MMMM'),
    value: i + 1,
  }))
}

export function BudgetsPage() {
  const today = dayjs()

  const [budgets, setBudgets] = useState<Budget[]>([])
  const [categories, setCategories] = useState<BudgetCategory[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [categoryFilter, setCategoryFilter] = useState<string | undefined>(undefined)
  const [year, setYear] = useState(today.year())
  const [period, setPeriod] = useState(today.month() + 1)

  const [formOpen, setFormOpen] = useState(false)
  const [formBudget, setFormBudget] = useState<Budget | null>(null)
  const [formLoading, setFormLoading] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [form] = Form.useForm()

  const [detailBudget, setDetailBudget] = useState<Budget | null>(null)
  const [detailItems, setDetailItems] = useState<BudgetSpendDetailItem[]>([])
  const [detailLoading, setDetailLoading] = useState(false)

  useEffect(() => {
    getBudgetCategories().then(setCategories).catch(() => setCategories([]))
  }, [])

  const load = () => {
    setLoading(true)
    setError(null)
    getBudgets({ category: categoryFilter, year, period })
      .then(setBudgets)
      .catch((e: unknown) => setError(String(e)))
      .finally(() => setLoading(false))
  }

  useEffect(load, [categoryFilter, year, period])

  const openCreate = () => {
    setFormBudget(null)
    setFormError(null)
    form.resetFields()
    form.setFieldsValue({ currency: 'UZS', is_active: true, period_type: 'monthly' })
    setFormOpen(true)
  }

  const openEdit = (b: Budget) => {
    setFormBudget(b)
    setFormError(null)
    form.setFieldsValue({
      name: b.name,
      category: b.category,
      period_type: b.period_type,
      limit_amount: parseFloat(b.limit_amount),
      currency: b.currency,
      is_active: b.is_active,
    })
    setFormOpen(true)
  }

  const handleFormSubmit = async () => {
    let values: BudgetCreatePayload & { limit_amount: number }
    try {
      values = await form.validateFields()
    } catch {
      return
    }
    setFormLoading(true)
    setFormError(null)
    try {
      const payload: BudgetCreatePayload = { ...values, limit_amount: String(values.limit_amount) }
      if (formBudget) {
        await updateBudget(formBudget.id, payload)
      } else {
        await createBudget(payload)
      }
      setFormOpen(false)
      load()
    } catch (e: unknown) {
      setFormError(String(e))
    } finally {
      setFormLoading(false)
    }
  }

  const handleDelete = (b: Budget) => {
    Modal.confirm({
      title: `Удалить бюджет «${b.name}»?`,
      okText: 'Удалить',
      okButtonProps: { danger: true },
      cancelText: 'Отмена',
      onOk: async () => {
        await deleteBudget(b.id)
        load()
      },
    })
  }

  const openDetail = async (b: Budget) => {
    setDetailBudget(b)
    setDetailItems([])
    setDetailLoading(true)
    try {
      const items = await getBudgetSpendDetail(b.id, { year, period })
      setDetailItems(items)
    } finally {
      setDetailLoading(false)
    }
  }

  const yearOptions = Array.from({ length: 5 }, (_, i) => {
    const y = today.year() - 2 + i
    return { label: String(y), value: y }
  })

  const columns: ColumnsType<Budget> = [
    {
      title: 'Название',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, row) => (
        <Space direction="vertical" size={0}>
          <Text strong>{name}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>{row.category_name}</Text>
        </Space>
      ),
    },
    {
      title: 'Период',
      dataIndex: 'period_type',
      key: 'period_type',
      width: 130,
      render: (pt: BudgetPeriodType) => PERIOD_LABELS[pt] ?? pt,
    },
    {
      title: 'Лимит',
      key: 'limit',
      width: 160,
      render: (_: unknown, row) => `${Number(row.limit_amount).toLocaleString('ru-RU')} ${row.currency}`,
    },
    {
      title: 'Израсходовано',
      key: 'spent',
      width: 220,
      render: (_: unknown, row) => {
        const pct = row.utilization_pct
        return (
          <Space direction="vertical" size={2} style={{ width: '100%' }}>
            <Progress
              percent={Math.min(pct, 100)}
              strokeColor={utilizationColor(pct)}
              size="small"
              format={() => `${pct}%`}
            />
            <Text style={{ fontSize: 12 }}>
              {Number(row.spent_amount).toLocaleString('ru-RU')} / {Number(row.limit_amount).toLocaleString('ru-RU')} {row.currency}
            </Text>
          </Space>
        )
      },
    },
    {
      title: 'Остаток',
      key: 'remaining',
      width: 140,
      render: (_: unknown, row) => {
        const rem = Number(row.remaining_amount)
        return (
          <Tag color={rem >= 0 ? 'green' : 'red'}>
            {rem.toLocaleString('ru-RU')} {row.currency}
          </Tag>
        )
      },
    },
    {
      title: 'Статус',
      dataIndex: 'is_active',
      key: 'is_active',
      width: 90,
      render: (active: boolean) => <Tag color={active ? 'blue' : 'default'}>{active ? 'Активен' : 'Неактивен'}</Tag>,
    },
    {
      title: '',
      key: 'actions',
      width: 110,
      render: (_: unknown, row) => (
        <Space>
          <Button size="small" icon={<UnorderedListOutlined />} onClick={() => openDetail(row)} title="Расходы" />
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(row)} />
          <Button size="small" danger icon={<DeleteOutlined />} onClick={() => handleDelete(row)} />
        </Space>
      ),
    },
  ]

  const detailColumns: ColumnsType<BudgetSpendDetailItem> = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60 },
    { title: 'Название', dataIndex: 'title', key: 'title' },
    {
      title: 'Сумма',
      key: 'amount',
      width: 140,
      render: (_: unknown, row) => `${Number(row.amount).toLocaleString('ru-RU')} ${row.currency}`,
    },
    { title: 'Статус', dataIndex: 'status', key: 'status', width: 100 },
    {
      title: 'Дата биллинга',
      dataIndex: 'billing_date',
      key: 'billing_date',
      width: 140,
      render: (v: string) => dayjs(v).format('MM.YYYY'),
    },
  ]

  return (
    <div>
      <Space align="center" style={{ marginBottom: 16 }} wrap>
        <Title level={4} style={{ margin: 0 }}>Бюджеты</Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          Добавить бюджет
        </Button>
      </Space>

      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          allowClear
          placeholder="Все категории"
          style={{ width: 220 }}
          value={categoryFilter}
          onChange={setCategoryFilter}
          options={categories.map((c) => ({ label: c.name, value: c.name }))}
        />
        <Select
          style={{ width: 100 }}
          value={year}
          onChange={(v) => { setYear(v); setPeriod(1) }}
          options={yearOptions}
        />
        <Select
          style={{ width: 150 }}
          value={period}
          onChange={setPeriod}
          options={monthOptions(year)}
        />
      </Space>

      {error && <Alert type="error" message={error} style={{ marginBottom: 16 }} />}

      <Table
        rowKey="id"
        dataSource={budgets}
        columns={columns}
        loading={loading}
        pagination={{ pageSize: 20 }}
        size="middle"
      />

      <Modal
        open={formOpen}
        title={formBudget ? 'Редактировать бюджет' : 'Новый бюджет'}
        onCancel={() => setFormOpen(false)}
        onOk={handleFormSubmit}
        okText={formBudget ? 'Сохранить' : 'Создать'}
        confirmLoading={formLoading}
        destroyOnClose
      >
        {formError && <Alert type="error" message={formError} style={{ marginBottom: 12 }} />}
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="Название" rules={[{ required: true, message: 'Укажите название' }]}>
            <Input placeholder="Например: Маркетинг Q1 2026" />
          </Form.Item>
          <Form.Item name="category" label="Категория" rules={[{ required: true, message: 'Выберите категорию' }]}>
            <Select
              placeholder="Выберите категорию"
              options={categories.map((c) => ({ label: c.name, value: c.id }))}
            />
          </Form.Item>
          <Form.Item name="period_type" label="Тип периода" rules={[{ required: true }]}>
            <Select options={Object.entries(PERIOD_LABELS).map(([v, l]) => ({ value: v, label: l }))} />
          </Form.Item>
          <Form.Item name="limit_amount" label="Лимит" rules={[{ required: true, message: 'Укажите лимит' }]}>
            <InputNumber style={{ width: '100%' }} min={0} precision={2} />
          </Form.Item>
          <Form.Item name="currency" label="Валюта" rules={[{ required: true }]}>
            <Select options={CURRENCIES.map((c) => ({ value: c, label: c }))} />
          </Form.Item>
          <Form.Item name="is_active" label="Активен" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        open={!!detailBudget}
        onClose={() => setDetailBudget(null)}
        title={detailBudget ? `Расходы: ${detailBudget.name}` : ''}
        width={640}
      >
        <Table
          rowKey="id"
          dataSource={detailItems}
          columns={detailColumns}
          loading={detailLoading}
          pagination={{ pageSize: 20 }}
          size="small"
        />
      </Drawer>
    </div>
  )
}
