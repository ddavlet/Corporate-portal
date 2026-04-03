import { useEffect, useState } from 'react'
import { Alert, Button, Card, Checkbox, Divider, Input, InputNumber, Select, Space, Typography, message } from 'antd'
import { ArrowLeftOutlined, PlusOutlined, SaveOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import {
  getAutoRequestConfig,
  updateAutoRequestConfig,
  type AutoRequestBillingMonthMode,
  type AutoRequestConfigResponse,
  type AutoRequestTemplateItem,
  type RequestFormConfigPaymentTypeItem,
} from '../../lib/api'
import { labelBlockAboveField } from '../formSpacing'

const PAYMENT_TYPES_FALLBACK = ['Наличные', 'Перечисление', 'Пополнение', 'Платежная карта'] as const

const BILLING_MONTH_OPTIONS: { value: AutoRequestBillingMonthMode; label: string }[] = [
  { value: 'previous', label: 'Предыдущий месяц' },
  { value: 'current', label: 'Этот месяц' },
  { value: 'next', label: 'Следующий месяц' },
]

function vendorKindForPaymentType(paymentType: string): 'cash' | 'transfer' {
  return paymentType === 'Наличные' ? 'cash' : 'transfer'
}

function paymentTypeSelectOptions(data: AutoRequestConfigResponse | null) {
  const pts = (data?.form_payment_types || []).filter((p) => p.is_enabled)
  if (pts.length) return pts.map((p) => ({ value: p.payment_type, label: p.payment_type }))
  return PAYMENT_TYPES_FALLBACK.map((v) => ({ value: v, label: v }))
}

function defaultPaymentTypeForNew(data: AutoRequestConfigResponse | null): string {
  const pts = (data?.form_payment_types || []).filter((p) => p.is_enabled)
  return pts[0]?.payment_type || 'Наличные'
}

function formPtForPaymentType(
  data: AutoRequestConfigResponse | null,
  paymentType: string,
): RequestFormConfigPaymentTypeItem | undefined {
  return data?.form_payment_types?.find((p) => p.payment_type === paymentType && p.is_enabled)
}

function vendorSelectOptions(row: AutoRequestTemplateItem, data: AutoRequestConfigResponse | null) {
  const kind = vendorKindForPaymentType(row.payment_type)
  const pt = formPtForPaymentType(data, row.payment_type)
  let list = (data?.vendor_candidates || []).filter((v) => v.kind === kind)
  if (pt?.vendor_ids?.length) {
    const allow = new Set(pt.vendor_ids)
    list = list.filter((v) => allow.has(v.id))
  }
  return list.map((v) => {
    const bits = [v.kind === 'cash' ? 'Наличные' : 'Перечисление', v.name]
    if (v.inn) bits.push(`ИНН ${v.inn}`)
    return { value: v.id, label: bits.join(' · ') }
  })
}

function purposeSelectOptions(row: AutoRequestTemplateItem, data: AutoRequestConfigResponse | null) {
  const pt = formPtForPaymentType(data, row.payment_type)
  return (pt?.payment_purposes || [])
    .filter((p) => p.is_active !== false)
    .map((p) => ({
      value: p.name,
      label: p.category ? `${p.name} (${p.category})` : p.name,
    }))
}

function emptyTemplate(paymentType: string): AutoRequestTemplateItem {
  return {
    is_enabled: false,
    name: '',
    payment_type: paymentType,
    day_of_month: 1,
    title_template: '',
    description_template: '',
    amount: null,
    currency: 'UZS',
    urgency: 'Обычно',
    payment_purpose: '',
    vendor_ref_id: null,
    billing_month_mode: 'current',
  }
}

export function AutoRequestsConfigPage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<AutoRequestConfigResponse | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setError(null)
      try {
        const resp = await getAutoRequestConfig()
        if (!cancelled) {
          setData({
            ...resp,
            form_payment_types: resp.form_payment_types ?? [],
          })
        }
      } catch (e: any) {
        if (!cancelled) setError(e?.message || 'Ошибка загрузки')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const hasFormConfig = Boolean(data?.form_payment_types?.length)

  const updateRow = (idx: number, patch: Partial<AutoRequestTemplateItem>) => {
    setData((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        templates: prev.templates.map((row, i) => (i === idx ? { ...row, ...patch } : row)),
      }
    })
  }

  const addTemplate = () => {
    setData((prev) => {
      if (!prev) return prev
      const pt = defaultPaymentTypeForNew(prev)
      return { ...prev, templates: [...prev.templates, emptyTemplate(pt)] }
    })
  }

  const removeTemplate = (idx: number) => {
    setData((prev) => {
      if (!prev) return prev
      return { ...prev, templates: prev.templates.filter((_, i) => i !== idx) }
    })
  }

  const save = async () => {
    if (!data) return
    setSaving(true)
    setError(null)
    try {
      const payload = {
        templates: data.templates.map((row) => ({
          id: row.id,
          is_enabled: row.is_enabled,
          name: String(row.name || '').trim(),
          payment_type: row.payment_type,
          day_of_month: row.day_of_month || 1,
          title_template: String(row.title_template || ''),
          description_template: String(row.description_template || ''),
          amount: row.amount == null || row.amount === '' ? null : row.amount,
          currency: row.currency || 'UZS',
          urgency: row.urgency || 'Обычно',
          payment_purpose: String(row.payment_purpose || ''),
          vendor_ref_id: row.vendor_ref_id ?? null,
          billing_month_mode: (row.billing_month_mode ?? 'current') as AutoRequestBillingMonthMode,
        })),
      }
      const next = await updateAutoRequestConfig(payload)
      setData({ ...next, form_payment_types: next.form_payment_types ?? [] })
      message.success('Сохранено')
    } catch (e: any) {
      setError(e?.message || 'Ошибка сохранения')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card>
      <Button type="link" icon={<ArrowLeftOutlined />} onClick={() => navigate('/requests')} style={{ padding: 0 }}>
        Назад к заявкам
      </Button>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Автозаявки
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        Один раз настраиваете поля как в обычной заявке: тип оплаты, поставщик, назначение, сумма и т.д. В выбранный день
        месяца система создаёт заявку. Месяц начисления в заявке задаётся отдельно (предыдущий / текущий / следующий
        относительно этого календарного месяца); токены вроде{' '}
        <Typography.Text code>{'{{billing_month_ru}}'}</Typography.Text> в заголовке и описании используют выбранный
        месяц. Заявитель в таких заявках всегда системный пользователь{' '}
        <Typography.Text code>app</Typography.Text>. Компания-плательщик не задаётся здесь: она настраивается только в
        разделе{' '}
        <Typography.Text strong>Настройка формы заявки</Typography.Text> (поле «Компания-плательщик» для соответствующего
        типа оплаты на вкладке типа).
      </Typography.Paragraph>
      <Divider />
      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} /> : null}
      {!loading && !hasFormConfig ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="Сначала настройте форму заявки (типы оплаты, поставщики, назначения), иначе сохранение шаблонов может быть недоступно."
        />
      ) : null}
      {loading ? (
        <Typography.Text type="secondary">Загрузка...</Typography.Text>
      ) : (
        <Space direction="vertical" size={12} style={{ display: 'flex' }}>
          <Button icon={<PlusOutlined />} onClick={addTemplate}>
            Добавить автозаявку
          </Button>
          {(data?.templates || []).map((row, idx) => {
            const pt = formPtForPaymentType(data, row.payment_type)
            const purposeOpts = purposeSelectOptions(row, data)
            const vendorOpts = vendorSelectOptions(row, data)
            return (
              <Card key={row.id ?? `new-${idx}`} size="small">
                <Space direction="vertical" size={10} style={{ display: 'flex' }}>
                  <Space align="center" wrap>
                    <Typography.Text strong>Шаблон #{idx + 1}</Typography.Text>
                    <Checkbox checked={row.is_enabled} onChange={(e) => updateRow(idx, { is_enabled: e.target.checked })}>
                      Активно
                    </Checkbox>
                    <Button danger onClick={() => removeTemplate(idx)}>
                      Удалить
                    </Button>
                  </Space>
                  <Input
                    placeholder="Название шаблона (для себя)"
                    value={row.name}
                    onChange={(e) => updateRow(idx, { name: e.target.value })}
                  />
                  <Space wrap size={12}>
                    <div>
                      <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 4 }}>
                        Тип оплаты
                      </Typography.Text>
                      <Select
                        style={{ width: 200 }}
                        value={row.payment_type}
                        onChange={(v) =>
                          updateRow(idx, {
                            payment_type: v,
                            vendor_ref_id: null,
                            payment_purpose: '',
                          })
                        }
                        options={paymentTypeSelectOptions(data)}
                      />
                    </div>
                    <InputNumber
                      min={1}
                      max={31}
                      value={row.day_of_month}
                      onChange={(v) => updateRow(idx, { day_of_month: typeof v === 'number' ? v : 1 })}
                      addonBefore="День месяца"
                    />
                    <div>
                      <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 4 }}>
                        Месяц начисления
                      </Typography.Text>
                      <Select
                        style={{ width: 220 }}
                        value={(row.billing_month_mode ?? 'current') as AutoRequestBillingMonthMode}
                        onChange={(v) => updateRow(idx, { billing_month_mode: v })}
                        options={BILLING_MONTH_OPTIONS}
                      />
                    </div>
                  </Space>
                  {pt?.default_company_payer ? (
                    <Typography.Text type="secondary">
                      В создаваемой заявке плательщик будет: «{pt.default_company_payer}» — задано в «Настройка формы
                      заявки» для типа «{row.payment_type}»
                    </Typography.Text>
                  ) : (
                    <Typography.Text type="secondary">
                      Для типа «{row.payment_type}» в «Настройка формы заявки» не задана компания-плательщик — в заявке
                      поле может остаться пустым.
                    </Typography.Text>
                  )}
                  <div>
                    <Typography.Text strong style={labelBlockAboveField}>
                      Поставщик
                    </Typography.Text>
                    <Select
                      style={{ width: '100%' }}
                      placeholder="Выберите из справочника"
                      value={row.vendor_ref_id ?? undefined}
                      onChange={(v) => updateRow(idx, { vendor_ref_id: v })}
                      options={vendorOpts}
                      allowClear
                      showSearch
                      optionFilterProp="label"
                    />
                  </div>
                  <div>
                    <Typography.Text strong style={labelBlockAboveField}>
                      Назначение платежа
                    </Typography.Text>
                    {purposeOpts.length > 0 ? (
                      <Select
                        style={{ width: '100%' }}
                        placeholder="Выберите назначение"
                        value={row.payment_purpose || undefined}
                        onChange={(v) => updateRow(idx, { payment_purpose: v })}
                        options={purposeOpts}
                        allowClear
                        showSearch
                        optionFilterProp="label"
                      />
                    ) : (
                      <Input
                        placeholder="Назначение (в настройках формы нет списка — ввод вручную)"
                        value={row.payment_purpose}
                        onChange={(e) => updateRow(idx, { payment_purpose: e.target.value })}
                      />
                    )}
                  </div>
                  <Input
                    placeholder="Заголовок (токены {{billing_month_ru}}, {{billing_month:%B %Y}}, {{now:%d.%m.%Y}})"
                    value={row.title_template}
                    onChange={(e) => updateRow(idx, { title_template: e.target.value })}
                  />
                  <Input.TextArea
                    rows={3}
                    placeholder="Описание шаблона с токенами даты"
                    value={row.description_template}
                    onChange={(e) => updateRow(idx, { description_template: e.target.value })}
                  />
                  <Space wrap size={12}>
                    <InputNumber
                      style={{ width: 150 }}
                      min={0}
                      placeholder="Сумма"
                      value={row.amount == null ? undefined : Number(row.amount)}
                      onChange={(v) => updateRow(idx, { amount: v == null ? null : String(v) })}
                    />
                    <Select
                      style={{ width: 120 }}
                      value={row.currency}
                      onChange={(v) => updateRow(idx, { currency: v })}
                      options={['UZS', 'USD', 'EUR', 'RUB'].map((v) => ({ value: v, label: v }))}
                    />
                    <Select
                      style={{ width: 140 }}
                      value={row.urgency}
                      onChange={(v) => updateRow(idx, { urgency: v })}
                      options={['Низко', 'Обычно', 'Срочно'].map((v) => ({ value: v, label: v }))}
                    />
                  </Space>
                  <Typography.Text type="secondary" style={labelBlockAboveField}>
                    Последний запуск: {row.last_run_month || 'еще не запускалось'}
                  </Typography.Text>
                </Space>
              </Card>
            )
          })}
          <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={save}>
            Сохранить
          </Button>
        </Space>
      )}
    </Card>
  )
}
