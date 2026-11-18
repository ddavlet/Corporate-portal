import { useEffect, useState } from 'react'
import { Alert, Form, Input, Modal, Select, Spin, Switch, message } from 'antd'
import {
  CardAutoRequestConfigUnavailableError,
  getCardAutoRequestConfig,
  saveCardAutoRequestConfig,
  type CardAutoRequestConfigResponse,
} from '../../lib/cardAutoRequestApi'

type FormValues = {
  is_enabled: boolean
  payment_purpose?: string
  category?: string
  company_payer?: string
  vendor_ref_id?: number | null
  match_text?: string
}

type Props = {
  walletId: number | null
  onClose: () => void
}

export function CardAutoRequestSettingsModal({ walletId, onClose }: Props) {
  const [form] = Form.useForm<FormValues>()
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [config, setConfig] = useState<CardAutoRequestConfigResponse | null>(null)
  const [unavailable, setUnavailable] = useState<'forbidden' | 'unavailable' | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const purpose = Form.useWatch('payment_purpose', form)

  useEffect(() => {
    if (walletId == null) return
    let cancelled = false
    setLoading(true)
    setConfig(null)
    setUnavailable(null)
    setLoadError(null)
    getCardAutoRequestConfig(walletId)
      .then((c) => {
        if (cancelled) return
        setConfig(c)
        form.setFieldsValue({
          is_enabled: c.is_enabled,
          payment_purpose: c.payment_purpose || undefined,
          category: c.category,
          company_payer: c.company_payer,
          vendor_ref_id: c.vendor_ref_id,
          match_text: c.match_text,
        })
      })
      .catch((e: unknown) => {
        if (cancelled) return
        if (e instanceof CardAutoRequestConfigUnavailableError) setUnavailable(e.reason)
        else setLoadError(e instanceof Error ? e.message : 'Ошибка загрузки')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [walletId, form])

  const submit = async () => {
    if (walletId == null) return
    try {
      const v = await form.validateFields()
      setSaving(true)
      await saveCardAutoRequestConfig(walletId, {
        is_enabled: v.is_enabled,
        payment_purpose: v.payment_purpose ?? '',
        category: (v.category ?? '').trim(),
        company_payer: (v.company_payer ?? '').trim(),
        vendor_ref_id: v.vendor_ref_id ?? null,
        match_text: (v.match_text ?? '').trim(),
      })
      message.success('Сохранено')
      onClose()
    } catch (e: unknown) {
      if (e && typeof e === 'object' && 'errorFields' in e) return
      if (e instanceof CardAutoRequestConfigUnavailableError) setUnavailable(e.reason)
      else message.error(e instanceof Error ? e.message : 'Ошибка сохранения')
    } finally {
      setSaving(false)
    }
  }

  const purposes = config?.options.payment_purposes ?? []
  const categoryPlaceholder = purposes.find((p) => p.name === purpose)?.category || 'Из назначения'
  const showForm = !!config && !unavailable

  return (
    <Modal
      title={`Автозаявки по расходам карты${config?.wallet_label ? `: ${config.wallet_label}` : ''}`}
      open={walletId != null}
      onCancel={onClose}
      onOk={() => void submit()}
      okText="Сохранить"
      cancelText="Отмена"
      okButtonProps={{ disabled: !showForm, loading: saving }}
      destroyOnClose
    >
      {loading ? (
        <div data-testid="card-auto-request-loading" style={{ textAlign: 'center', padding: 24 }}>
          <Spin />
        </div>
      ) : null}
      {unavailable === 'forbidden' ? (
        <Alert type="warning" showIcon message="Настройку автозаявок меняет только администратор компании" />
      ) : null}
      {unavailable === 'unavailable' ? <Alert type="info" showIcon message="Модуль недоступен" /> : null}
      {loadError ? <Alert type="error" showIcon message={loadError} /> : null}
      <Form form={form} layout="vertical" style={showForm ? undefined : { display: 'none' }}>
        <Form.Item name="is_enabled" label="Создавать заявки автоматически" valuePropName="checked">
          <Switch />
        </Form.Item>
        <Form.Item
          noStyle
          shouldUpdate={(a, b) => a.is_enabled !== b.is_enabled}
        >
          {({ getFieldValue }) => (
            <Form.Item
              name="payment_purpose"
              label="Назначение платежа"
              rules={[{ required: !!getFieldValue('is_enabled'), message: 'Выберите назначение' }]}
            >
              <Select
                allowClear
                showSearch
                placeholder="Назначение"
                notFoundContent="Справочник назначений пуст"
                options={purposes.map((p) => ({ value: p.name, label: p.name }))}
              />
            </Form.Item>
          )}
        </Form.Item>
        <Form.Item name="category" label="Категория">
          <Input placeholder={categoryPlaceholder} maxLength={100} />
        </Form.Item>
        <Form.Item name="company_payer" label="Компания-плательщик">
          <Input placeholder={config?.options.default_company_payer || ''} maxLength={100} />
        </Form.Item>
        <Form.Item name="vendor_ref_id" label="Контрагент">
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="Не выбран"
            options={(config?.options.vendors ?? []).map((v) => ({ value: v.id, label: v.name }))}
          />
        </Form.Item>
        <Form.Item
          name="match_text"
          label="Описание содержит"
          extra="Только расходы, в описании которых есть этот текст (без учёта регистра). Пусто — все расходы карты."
        >
          <Input maxLength={200} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
