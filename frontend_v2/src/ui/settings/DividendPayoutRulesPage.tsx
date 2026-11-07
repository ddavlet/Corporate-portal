import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  AutoComplete,
  Button,
  Card,
  Divider,
  Empty,
  Form,
  Modal,
  Popconfirm,
  Select,
  Skeleton,
  Space,
  Switch,
  Table,
  Typography,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { ArrowLeftOutlined, DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'

import {
  DividendPayoutsApiError,
  createDividendPayoutRule,
  deleteDividendPayoutRule,
  getDividendPayoutOptions,
  listDividendPayoutRules,
  updateDividendPayoutRule,
  type DividendPayoutOptions,
  type DividendPayoutRule,
  type DividendPayoutRuleDto,
} from '../../lib/dividendPayoutsApi'

const FALLBACK_RECIPIENTS = [
  { value: 'инвестор', label: 'Учредитель (инвестор)' },
  { value: 'партнер', label: 'Партнёр' },
]

const EMPTY_OPTIONS: DividendPayoutOptions = { return_types: [], recipients: [], payment_purposes: [] }

const FORM_FIELDS: Array<keyof DividendPayoutRuleDto> = ['payment_purpose', 'return_type', 'recipient', 'is_active']

function errorText(e: unknown, fallback: string): string {
  return e instanceof Error && e.message ? e.message : fallback
}

type PurposeCellProps = {
  value: string
  options: Array<{ value: string }>
  disabled: boolean
  onCommit: (next: string) => Promise<boolean>
}

/** Назначение платежа в строке: правка локально, сохранение при выборе подсказки или потере фокуса. */
function PurposeCell({ value, options, disabled, onCommit }: PurposeCellProps) {
  const [draft, setDraft] = useState(value)
  useEffect(() => setDraft(value), [value])
  const commit = (next: string) => {
    const trimmed = next.trim()
    if (!trimmed || trimmed === value) {
      setDraft(value)
      return
    }
    void onCommit(trimmed).then((ok) => {
      if (!ok) setDraft(value)
    })
  }
  return (
    <AutoComplete
      style={{ width: '100%', minWidth: 220 }}
      value={draft}
      options={options}
      disabled={disabled}
      onChange={(v) => setDraft(v)}
      onSelect={(v: string) => commit(v)}
      onBlur={() => commit(draft)}
      filterOption={(input, option) => String(option?.value ?? '').toLowerCase().includes(input.toLowerCase())}
    />
  )
}

export function DividendPayoutRulesPage() {
  const navigate = useNavigate()
  const [form] = Form.useForm<DividendPayoutRuleDto>()
  const [loading, setLoading] = useState(true)
  const [unavailable, setUnavailable] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [rules, setRules] = useState<DividendPayoutRule[]>([])
  const [options, setOptions] = useState<DividendPayoutOptions>(EMPTY_OPTIONS)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const [loadedRules, loadedOptions] = await Promise.all([listDividendPayoutRules(), getDividendPayoutOptions()])
        if (cancelled) return
        setRules(loadedRules)
        setOptions(loadedOptions)
      } catch (e: unknown) {
        if (cancelled) return
        if (e instanceof DividendPayoutsApiError && e.status === 404) setUnavailable(true)
        else setError(errorText(e, 'Ошибка загрузки'))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const purposeOptions = useMemo(() => options.payment_purposes.map((p) => ({ value: p })), [options.payment_purposes])
  const returnTypeOptions = options.return_types
  const recipientOptions = options.recipients.length ? options.recipients : FALLBACK_RECIPIENTS

  const patchRule = async (rule: DividendPayoutRule, patch: Partial<DividendPayoutRuleDto>): Promise<boolean> => {
    setBusyId(rule.id)
    setError(null)
    try {
      const updated = await updateDividendPayoutRule(rule.id, patch)
      setRules((prev) => prev.map((r) => (r.id === updated.id ? updated : r)))
      message.success('Сохранено')
      return true
    } catch (e: unknown) {
      setError(errorText(e, 'Ошибка сохранения'))
      return false
    } finally {
      setBusyId(null)
    }
  }

  const removeRule = async (rule: DividendPayoutRule) => {
    setBusyId(rule.id)
    setError(null)
    try {
      await deleteDividendPayoutRule(rule.id)
      setRules((prev) => prev.filter((r) => r.id !== rule.id))
      message.success('Правило удалено')
    } catch (e: unknown) {
      setError(errorText(e, 'Ошибка удаления'))
    } finally {
      setBusyId(null)
    }
  }

  const openCreate = () => {
    setCreateError(null)
    form.resetFields()
    form.setFieldsValue({
      payment_purpose: '',
      return_type: returnTypeOptions[0]?.value,
      recipient: recipientOptions[0]?.value,
      is_active: true,
    })
    setModalOpen(true)
  }

  const submitCreate = async () => {
    let values: DividendPayoutRuleDto
    try {
      values = await form.validateFields()
    } catch {
      return
    }
    setCreating(true)
    setCreateError(null)
    try {
      const created = await createDividendPayoutRule({
        payment_purpose: values.payment_purpose.trim(),
        return_type: values.return_type,
        recipient: values.recipient,
        is_active: values.is_active,
      })
      setRules((prev) => [...prev, created])
      setModalOpen(false)
      message.success('Правило добавлено')
    } catch (e: unknown) {
      if (e instanceof DividendPayoutsApiError) {
        const known = FORM_FIELDS.filter((f) => e.fieldErrors[f]?.length)
        form.setFields(known.map((f) => ({ name: f, errors: e.fieldErrors[f] })))
        const unknownErrors = Object.entries(e.fieldErrors)
          .filter(([key]) => !FORM_FIELDS.includes(key as keyof DividendPayoutRuleDto))
          .flatMap(([, msgs]) => msgs)
        if (unknownErrors.length) setCreateError(unknownErrors.join(' '))
        else if (!known.length) setCreateError(e.message)
      } else {
        setCreateError(errorText(e, 'Ошибка сохранения'))
      }
    } finally {
      setCreating(false)
    }
  }

  const columns: ColumnsType<DividendPayoutRule> = [
    {
      title: 'Назначение платежа',
      dataIndex: 'payment_purpose',
      key: 'payment_purpose',
      render: (_: unknown, rule) => (
        <PurposeCell
          value={rule.payment_purpose}
          options={purposeOptions}
          disabled={busyId === rule.id}
          onCommit={(next) => patchRule(rule, { payment_purpose: next })}
        />
      ),
    },
    {
      title: 'Тип выплаты',
      dataIndex: 'return_type',
      key: 'return_type',
      width: 220,
      render: (_: unknown, rule) => (
        <Select
          style={{ width: '100%' }}
          value={rule.return_type}
          options={returnTypeOptions}
          disabled={busyId === rule.id}
          onChange={(v: string) => void patchRule(rule, { return_type: v })}
        />
      ),
    },
    {
      title: 'Получатель',
      dataIndex: 'recipient',
      key: 'recipient',
      width: 220,
      render: (_: unknown, rule) => (
        <Select
          style={{ width: '100%' }}
          value={rule.recipient}
          options={recipientOptions}
          disabled={busyId === rule.id}
          onChange={(v: string) => void patchRule(rule, { recipient: v })}
        />
      ),
    },
    {
      title: 'Активно',
      dataIndex: 'is_active',
      key: 'is_active',
      width: 100,
      render: (_: unknown, rule) => (
        <Switch
          checked={rule.is_active}
          disabled={busyId === rule.id}
          onChange={(v) => void patchRule(rule, { is_active: v })}
        />
      ),
    },
    {
      key: 'actions',
      width: 60,
      render: (_: unknown, rule) => (
        <Popconfirm
          title="Удалить правило?"
          okText="Удалить"
          cancelText="Отмена"
          onConfirm={() => void removeRule(rule)}
        >
          <Button danger type="text" icon={<DeleteOutlined />} aria-label="Удалить правило" disabled={busyId === rule.id} />
        </Popconfirm>
      ),
    },
  ]

  const back = (
    <Button type="link" icon={<ArrowLeftOutlined />} onClick={() => navigate('/settings')} style={{ padding: 0 }}>
      Назад к настройкам
    </Button>
  )

  const header = (
    <>
      {back}
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Дивиденды: правила выплат
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        Когда заявка с указанным назначением оплачена, портал создаёт выплату инвестиций с выбранным типом и получателем.
        Способ оплаты не важен.
      </Typography.Paragraph>
      <Divider />
    </>
  )

  if (unavailable) {
    return (
      <Card>
        {header}
        <Alert
          type="warning"
          showIcon
          message="Модуль правил дивидендов недоступен"
          description="Модуль не включён для компании или ещё не развёрнут на сервере."
        />
      </Card>
    )
  }

  return (
    <Card>
      {header}
      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} closable onClose={() => setError(null)} /> : null}
      {loading ? (
        <Skeleton active />
      ) : (
        <Space direction="vertical" size={16} style={{ display: 'flex' }}>
          <div>
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              Добавить правило
            </Button>
          </div>
          <Table<DividendPayoutRule>
            rowKey="id"
            size="middle"
            pagination={false}
            columns={columns}
            dataSource={rules}
            scroll={{ x: 760 }}
            locale={{ emptyText: <Empty description="Правил пока нет" /> }}
          />
        </Space>
      )}

      <Modal
        title="Новое правило"
        open={modalOpen}
        okText="Сохранить"
        cancelText="Отмена"
        confirmLoading={creating}
        onOk={() => void submitCreate()}
        onCancel={() => setModalOpen(false)}
        forceRender
      >
        {createError ? <Alert type="error" showIcon message={createError} style={{ marginBottom: 12 }} /> : null}
        <Form form={form} layout="vertical">
          <Form.Item
            name="payment_purpose"
            label="Назначение платежа"
            rules={[{ required: true, whitespace: true, message: 'Укажите назначение платежа' }]}
          >
            <AutoComplete
              aria-label="Назначение платежа"
              options={purposeOptions}
              placeholder="Выберите или введите назначение"
              filterOption={(input, option) => String(option?.value ?? '').toLowerCase().includes(input.toLowerCase())}
            />
          </Form.Item>
          <Form.Item name="return_type" label="Тип выплаты" rules={[{ required: true, message: 'Выберите тип выплаты' }]}>
            <Select options={returnTypeOptions} placeholder="Тип выплаты" />
          </Form.Item>
          <Form.Item name="recipient" label="Получатель" rules={[{ required: true, message: 'Выберите получателя' }]}>
            <Select options={recipientOptions} placeholder="Получатель" />
          </Form.Item>
          <Form.Item name="is_active" label="Активно" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}
