import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Tabs,
  message,
  Space,
  Switch,
  Table,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  createBankAccount,
  createCashRegister,
  createCorporateCardAccount,
  deleteBankAccount,
  deleteCashRegister,
  deleteCorporateCardAccount,
  getBankAccounts,
  getCashRegisters,
  getCorporateCardAccounts,
  patchBankAccount,
  patchCashRegister,
  patchCorporateCardAccount,
  patchWallet,
  type BankAccountDto,
  type CashRegisterDto,
  type CorporateCardAccountDto,
  apiFetch,
  updateTenantCashExpenseIdFormat,
} from '../../lib/api'

function previewCashExpenseCanonicalId(prefix: string, digitWidth: number, sampleNumeric: number): string {
  const w = Number.isFinite(digitWidth) ? Math.min(32, Math.max(1, Math.floor(digitWidth))) : 9
  const core = String(Math.trunc(sampleNumeric)).padStart(w, '0')
  return `${prefix}${core}`
}

function CashExpenseExternalIdFormatSection() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [hidden, setHidden] = useState(false)
  const [form] = Form.useForm<{
    cash_expense_external_id_prefix: string
    cash_expense_external_id_digit_width: number
  }>()
  const prefixWatch = Form.useWatch('cash_expense_external_id_prefix', form)
  const widthWatch = Form.useWatch('cash_expense_external_id_digit_width', form)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiFetch('/api/tenant/cash-expense-id-format/')
      if (res.status === 403) {
        setHidden(true)
        return
      }
      if (!res.ok) {
        message.error(`Не удалось загрузить настройку формата (${res.status}).`)
        setHidden(false)
        return
      }
      const data = (await res.json()) as {
        cash_expense_external_id_prefix?: string
        cash_expense_external_id_digit_width?: number
      }
      form.setFieldsValue({
        cash_expense_external_id_prefix: data.cash_expense_external_id_prefix ?? '',
        cash_expense_external_id_digit_width: data.cash_expense_external_id_digit_width ?? 9,
      })
      setHidden(false)
    } finally {
      setLoading(false)
    }
  }, [form])

  useEffect(() => {
    void load()
  }, [load])

  if (hidden) return null

  const p = typeof prefixWatch === 'string' ? prefixWatch : ''
  const dw = typeof widthWatch === 'number' ? widthWatch : 9
  const preview = previewCashExpenseCanonicalId(p, dw, 459)

  const onSave = async () => {
    try {
      const v = await form.validateFields()
      setSaving(true)
      await updateTenantCashExpenseIdFormat({
        cash_expense_external_id_prefix: v.cash_expense_external_id_prefix.trim(),
        cash_expense_external_id_digit_width: v.cash_expense_external_id_digit_width,
      })
      message.success('Сохранено')
      void load()
    } catch (e: unknown) {
      if (e && typeof e === 'object' && 'errorFields' in e) return
      message.error(e instanceof Error ? e.message : 'Ошибка сохранения')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card title="Формат номера кассового расхода (external id)" style={{ marginBottom: 16 }} loading={loading}>
      <Typography.Paragraph type="secondary">
        Привязка расхода к заявке: можно ввести короткий номер (например <Typography.Text code>459</Typography.Text>),
        система найдёт строку по полному идентификатору в кассе, как он хранится в базе после загрузки/импорта.
      </Typography.Paragraph>
      <Form form={form} layout="vertical" disabled={loading}>
        <Form.Item
          label="Префикс перед номером"
          name="cash_expense_external_id_prefix"
          rules={[{ max: 32, message: 'Не длиннее 32 символов' }]}
          extra="Оставьте пустым, если в кассе только число с ведущими нулями. Пример с префиксом по умолчанию: «1-» → 1-000000343."
        >
          <Input placeholder="Например: 1- или пусто" allowClear />
        </Form.Item>
        <Form.Item
          label="Числовая часть: знаков всего"
          name="cash_expense_external_id_digit_width"
          rules={[{ required: true }]}
          extra="Сколько знаков занимает число после дополнения нулями слева (не считая префикс)."
        >
          <InputNumber min={1} max={32} style={{ width: '100%' }} />
        </Form.Item>
      </Form>
      <Typography.Paragraph style={{ marginBottom: 16 }}>
        Пример: ввод <Typography.Text code>459</Typography.Text> совпадает с расходом{' '}
        <Typography.Text code>{preview}</Typography.Text> в базе кассы (для указанной ширины и префикса).
      </Typography.Paragraph>
      <Button type="primary" onClick={() => void onSave()} loading={saving} disabled={loading}>
        Сохранить формат
      </Button>
    </Card>
  )
}

function CashTab() {
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
      setRows(await getCashRegisters())
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
    { title: 'ID кошелька', dataIndex: 'wallet_id', width: 110 },
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
    {
      title: 'Показывать в разделе "Касса"',
      dataIndex: 'wallet_is_visible_in_cash_section',
      width: 220,
      render: (v: boolean | undefined, r) => (
        <Switch
          checked={v !== false}
          onChange={async (checked) => {
            try {
              await patchWallet(r.wallet_id, { is_visible_in_cash_section: checked })
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
                content: 'Без операций по этой кассе. Иначе удаление будет отклонено.',
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
    <>
      <CashExpenseExternalIdFormatSection />
      <Typography.Paragraph type="secondary">
        Можно отключить показ отдельного кошелька в разделе "Касса" (остатки, доходы и расходы), не блокируя
        операции по нему.
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
          <Form.Item name="currency" label="Валюта" rules={[{ required: true, message: 'Укажите валюту' }]}>
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
          <Form form={openingForm} layout="vertical" initialValues={{ opening_balance: '' }}>
            <Typography.Text type="secondary">
              Кошелёк #{openingModalFor.wallet_id}, валюта {openingModalFor.currency}
            </Typography.Text>
            <Form.Item name="opening_balance" label="Остаток" rules={[{ required: true, message: 'Введите сумму' }]}>
              <Input />
            </Form.Item>
          </Form>
        ) : null}
      </Modal>
    </>
  )
}

function BankTab() {
  const [loading, setLoading] = useState(true)
  const [rows, setRows] = useState<BankAccountDto[]>([])
  const [error, setError] = useState<string | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<BankAccountDto | null>(null)
  const [openingFor, setOpeningFor] = useState<BankAccountDto | null>(null)
  const [form] = Form.useForm()
  const [openingForm] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setRows(await getBankAccounts())
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
    form.setFieldsValue({ label: 'Основной', account_no: '', mfo: '' })
    setModalOpen(true)
  }

  const openEdit = (r: BankAccountDto) => {
    setEditing(r)
    form.setFieldsValue({ label: r.label, account_no: r.account_no, mfo: r.mfo })
    setModalOpen(true)
  }

  const submitModal = async () => {
    try {
      const v = await form.validateFields()
      if (editing) {
        await patchBankAccount(editing.id, {
          label: v.label,
          account_no: v.account_no,
          mfo: v.mfo,
        })
        message.success('Сохранено')
      } else {
        await createBankAccount({
          label: v.label,
          account_no: v.account_no || '',
          mfo: v.mfo || '',
        })
        message.success('Банковский кошелёк создан')
      }
      setModalOpen(false)
      void load()
    } catch (e: unknown) {
      if (e && typeof e === 'object' && 'errorFields' in e) return
      message.error(e instanceof Error ? e.message : 'Ошибка')
    }
  }

  const submitOpening = async () => {
    if (!openingFor) return
    try {
      const v = await openingForm.validateFields()
      await patchWallet(openingFor.wallet_id, { opening_balance: String(v.opening_balance) })
      message.success('Остаток на 1 янв обновлён')
      setOpeningFor(null)
      openingForm.resetFields()
    } catch (e: unknown) {
      if (e && typeof e === 'object' && 'errorFields' in e) return
      message.error(e instanceof Error ? e.message : 'Ошибка')
    }
  }

  const columns: ColumnsType<BankAccountDto> = [
    { title: 'Название', dataIndex: 'label' },
    { title: 'ID кошелька', dataIndex: 'wallet_id', width: 110 },
    { title: 'Счёт (справочно)', dataIndex: 'account_no' },
    { title: 'МФО', dataIndex: 'mfo', width: 100 },
    { title: 'Валюта кошелька', key: 'cur', width: 120, render: () => 'UZS' },
    {
      title: '',
      key: 'actions',
      width: 220,
      render: (_, r) => (
        <Space>
          <Button size="small" onClick={() => openEdit(r)}>
            Изменить
          </Button>
          <Button size="small" onClick={() => setOpeningFor(r)}>
            Остаток 1 янв
          </Button>
          <Button
            size="small"
            danger
            onClick={() => {
              Modal.confirm({
                title: 'Удалить банковский кошелёк?',
                content: 'Только если нет операций по выписке.',
                onOk: async () => {
                  try {
                    await deleteBankAccount(r.id)
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
    <>
      <Typography.Paragraph type="secondary">
        Один банковский кошелёк на компанию (UZS). Поля счёта/МФО — справочные, не реквизиты контрагента из
        выписки.
      </Typography.Paragraph>
      {rows.length === 0 ? (
        <Button type="primary" onClick={openCreate} style={{ marginBottom: 16 }}>
          Создать банковский кошелёк
        </Button>
      ) : null}
      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} /> : null}
      <Table<BankAccountDto>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={rows}
        pagination={false}
      />

      <Modal
        title={editing ? 'Банк (выписка)' : 'Новый банковский кошелёк'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => void submitModal()}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item name="label" label="Название" rules={[{ required: true, message: 'Укажите название' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="account_no" label="Расчётный счёт (справочно)">
            <Input />
          </Form.Item>
          <Form.Item name="mfo" label="МФО (справочно)">
            <Input maxLength={10} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="Остаток на 1 января (кошелёк банка)"
        open={!!openingFor}
        onCancel={() => {
          setOpeningFor(null)
          openingForm.resetFields()
        }}
        onOk={() => void submitOpening()}
        destroyOnClose
      >
        {openingFor ? (
          <Form form={openingForm} layout="vertical" initialValues={{ opening_balance: '' }}>
            <Typography.Text type="secondary">Кошелёк #{openingFor.wallet_id}, валюта UZS</Typography.Text>
            <Form.Item name="opening_balance" label="Остаток" rules={[{ required: true, message: 'Введите сумму' }]}>
              <Input />
            </Form.Item>
          </Form>
        ) : null}
      </Modal>
    </>
  )
}

function CorpCardTab() {
  const [loading, setLoading] = useState(true)
  const [rows, setRows] = useState<CorporateCardAccountDto[]>([])
  const [error, setError] = useState<string | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<CorporateCardAccountDto | null>(null)
  const [openingModalFor, setOpeningModalFor] = useState<CorporateCardAccountDto | null>(null)
  const [form] = Form.useForm()
  const [openingForm] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setRows(await getCorporateCardAccounts())
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
    form.setFieldsValue({ label: '', external_ref: '' })
    setModalOpen(true)
  }

  const openEdit = (r: CorporateCardAccountDto) => {
    setEditing(r)
    form.setFieldsValue({ label: r.label, external_ref: r.external_ref })
    setModalOpen(true)
  }

  const submitModal = async () => {
    try {
      const v = await form.validateFields()
      if (editing) {
        await patchCorporateCardAccount(editing.id, {
          label: v.label,
          external_ref: v.external_ref,
        })
        message.success('Сохранено')
      } else {
        await createCorporateCardAccount({
          currency: v.currency,
          label: v.label,
          external_ref: v.external_ref,
        })
        message.success('Счёт корпкарты создан')
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

  const columns: ColumnsType<CorporateCardAccountDto> = [
    { title: 'Название', dataIndex: 'label', render: (v, r) => (v || '').trim() || r.currency },
    { title: 'ID кошелька', dataIndex: 'wallet_id', width: 110 },
    { title: 'Валюта', dataIndex: 'currency', width: 90 },
    { title: 'Внешний код', dataIndex: 'external_ref' },
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
                title: 'Удалить счёт корпкарты?',
                content: 'Только если нет операций по карте.',
                onOk: async () => {
                  try {
                    await deleteCorporateCardAccount(r.id)
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
    <>
      <Typography.Paragraph type="secondary">
        Один счёт корпоративной карты на валюту. Остаток на 1 января — в кошельке.
      </Typography.Paragraph>
      <Button type="primary" onClick={openCreate} style={{ marginBottom: 16 }}>
        Добавить счёт
      </Button>
      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} /> : null}
      <Table<CorporateCardAccountDto>
        rowKey="id"
        loading={loading}
        columns={columns}
        dataSource={rows}
        pagination={false}
      />

      <Modal
        title={editing ? 'Корпоративная карта' : 'Новый счёт'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={() => void submitModal()}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          {!editing ? (
            <Form.Item name="currency" label="Валюта" rules={[{ required: true, message: 'Укажите валюту' }]}>
              <Input maxLength={10} />
            </Form.Item>
          ) : null}
          <Form.Item name="label" label="Название">
            <Input />
          </Form.Item>
          <Form.Item name="external_ref" label="Внешний код / примечание">
            <Input />
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
          <Form form={openingForm} layout="vertical" initialValues={{ opening_balance: '' }}>
            <Typography.Text type="secondary">
              Кошелёк #{openingModalFor.wallet_id}, валюта {openingModalFor.currency}
            </Typography.Text>
            <Form.Item name="opening_balance" label="Остаток" rules={[{ required: true, message: 'Введите сумму' }]}>
              <Input />
            </Form.Item>
          </Form>
        ) : null}
      </Modal>
    </>
  )
}

export function CashRegistersSettingsPage() {
  return (
    <div style={{ maxWidth: 1100 }}>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Кошельки и счета
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
        Наличные: формат номера кассового расхода для заявок, кассы, банк (выписка) и корпоративная карта: создание,
        правка, безопасное удаление (без движений) и остаток на начало года.
      </Typography.Paragraph>
      <Tabs
        defaultActiveKey="cash"
        items={[
          { key: 'cash', label: 'Наличные (касса)', children: <CashTab /> },
          { key: 'bank', label: 'Банк (выписка)', children: <BankTab /> },
          { key: 'corp', label: 'Корпоративная карта', children: <CorpCardTab /> },
        ]}
      />
    </div>
  )
}
