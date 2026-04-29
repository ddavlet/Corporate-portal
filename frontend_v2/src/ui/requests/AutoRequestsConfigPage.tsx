import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Checkbox, Collapse, Divider, Input, InputNumber, Select, Space, Typography, message } from 'antd'
import { ArrowLeftOutlined, PlusOutlined, SaveOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import {
  createAutoRequestCopy,
  getAutoRequestConfig,
  updateAutoRequestConfig,
  listContracts,
  type AutoRequestBillingMonthMode,
  type AutoRequestConfigResponse,
  type AutoRequestTemplateItem,
  type RequestFormConfigCandidateUser,
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

function firstRequesterIdForPaymentType(
  data: AutoRequestConfigResponse | null,
  paymentType: string,
): number | undefined {
  const pt = formPtForPaymentType(data, paymentType)
  const ids = pt?.requester_ids ?? []
  if (ids.length) return ids[0]
  const c = data?.requester_candidates?.[0]
  return c?.id
}

function requesterSelectOptions(row: AutoRequestTemplateItem, data: AutoRequestConfigResponse | null) {
  const pt = formPtForPaymentType(data, row.payment_type)
  const subset = pt?.requester_ids ?? []
  const all: RequestFormConfigCandidateUser[] = data?.requester_candidates ?? []
  const list = subset.length ? all.filter((u) => subset.includes(u.id)) : all
  return list.map((u) => ({ value: u.id, label: u.username }))
}

function emptyTemplate(data: AutoRequestConfigResponse | null, paymentType: string): AutoRequestTemplateItem {
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
    contract_ref_id: null,
    billing_month_mode: 'current',
    requester_id: firstRequesterIdForPaymentType(data, paymentType),
  }
}

export function AutoRequestsConfigPage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [creatingTemplateId, setCreatingTemplateId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<AutoRequestConfigResponse | null>(null)
  const [contractOptsMap, setContractOptsMap] = useState<Record<number, { value: number; label: string }[]>>({})

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
            requester_candidates: resp.requester_candidates ?? [],
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

  const refreshContractsForIdx = useCallback(
    (idx: number, vendorId: number | null | undefined, paymentType: string) => {
      if (!data) return
      const pt = formPtForPaymentType(data, paymentType)
      if (!pt?.contracts_required || !vendorId) {
        setContractOptsMap((prev) => ({ ...prev, [idx]: [] }))
        return
      }
      listContracts({ vendor: vendorId })
        .then((rows) =>
          setContractOptsMap((prev) => ({
            ...prev,
            [idx]: rows.map((r) => ({
              value: r.id,
              label: `${r.contract_number} (${r.date_from})${r.is_expired ? ' просрочен' : ''}`,
            })),
          })),
        )
        .catch(() => setContractOptsMap((prev) => ({ ...prev, [idx]: [] })))
    },
    [data],
  )

  useEffect(() => {
    if (!data?.templates?.length) return
    data.templates.forEach((row, idx) => {
      refreshContractsForIdx(idx, row.vendor_ref_id, row.payment_type)
    })
  }, [data, refreshContractsForIdx])

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
      return { ...prev, templates: [...prev.templates, emptyTemplate(prev, pt)] }
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
    for (let i = 0; i < data.templates.length; i++) {
      const row = data.templates[i]
      if (row.requester_id == null || !Number.isFinite(Number(row.requester_id))) {
        message.warning(`Укажите заявителя для шаблона №${i + 1}`)
        return
      }
    }
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
          contract_ref_id: row.contract_ref_id ?? null,
          billing_month_mode: (row.billing_month_mode ?? 'current') as AutoRequestBillingMonthMode,
          requester_id: Number(row.requester_id),
        })),
      }
      const next = await updateAutoRequestConfig(payload)
      setData({
        ...next,
        form_payment_types: next.form_payment_types ?? [],
        requester_candidates: next.requester_candidates ?? [],
      })
      message.success('Сохранено')
    } catch (e: any) {
      setError(e?.message || 'Ошибка сохранения')
    } finally {
      setSaving(false)
    }
  }

  const createCopy = async (row: AutoRequestTemplateItem) => {
    if (!row.id) {
      message.warning('Сначала сохраните шаблон')
      return
    }
    setCreatingTemplateId(row.id)
    try {
      const created = await createAutoRequestCopy(row.id)
      message.success(`Копия создана: заявка #${created.request_id}`)
    } catch (e: any) {
      message.error(e?.message || 'Не удалось создать копию')
    } finally {
      setCreatingTemplateId(null)
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
        Один раз настраиваете поля как в обычной заявке: тип оплаты, заявитель, поставщик, назначение, сумма и т.д. В
        выбранный день месяца система создаёт заявку. Месяц начисления в заявке задаётся отдельно (предыдущий / текущий /
        следующий относительно этого календарного месяца); токены вроде{' '}
        <Typography.Text code>{'{{billing_month_ru}}'}</Typography.Text> в заголовке и описании используют выбранный
        месяц. Заявитель — из списка, разрешённого для типа оплаты в «Настройка формы заявки» (при уведомлении в Telegram
        о черновике без суммы используется{' '}
        <Typography.Text code>telegram_chat_id</Typography.Text> выбранного пользователя). Компания-плательщик не
        задаётся здесь: она настраивается только в разделе{' '}
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
            const templateTitle = String(row.name || '').trim() || `Шаблон #${idx + 1}`
            return (
              <Card key={row.id ?? `new-${idx}`} size="small">
                <Collapse
                  items={[
                    {
                      key: 'fields',
                      label: (
                        <Space size={10} wrap>
                          <Typography.Text strong>{templateTitle}</Typography.Text>
                          <Typography.Text type="secondary">({row.payment_type})</Typography.Text>
                        </Space>
                      ),
                      extra: (
                        <Space onClick={(e) => e.stopPropagation()}>
                          <Checkbox
                            checked={row.is_enabled}
                            onChange={(e) => updateRow(idx, { is_enabled: e.target.checked })}
                          >
                            Активно
                          </Checkbox>
                          <Button
                            size="small"
                            onClick={() => createCopy(row)}
                            loading={creatingTemplateId === row.id}
                            disabled={!row.id}
                          >
                            Создать копию
                          </Button>
                          <Button danger size="small" onClick={() => removeTemplate(idx)}>
                            Удалить
                          </Button>
                        </Space>
                      ),
                      children: (
                        <Space direction="vertical" size={10} style={{ display: 'flex' }}>
                          <Input
                            placeholder="Название шаблона (для себя)"
                            value={row.name}
                            onChange={(e) => updateRow(idx, { name: e.target.value })}
                          />
                          <Space wrap size={12} align="start">
                            <div>
                              <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 4 }}>
                                День месяца
                              </Typography.Text>
                              <InputNumber
                                min={1}
                                max={31}
                                style={{ width: 120 }}
                                value={row.day_of_month}
                                onChange={(v) => updateRow(idx, { day_of_month: typeof v === 'number' ? v : 1 })}
                              />
                            </div>
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
                          <Space wrap size={12} align="start">
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
                                    contract_ref_id: null,
                                    payment_purpose: '',
                                    requester_id: firstRequesterIdForPaymentType(data, v),
                                  })
                                }
                                options={paymentTypeSelectOptions(data)}
                              />
                            </div>
                            <div>
                              <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 4 }}>
                                Заявитель
                              </Typography.Text>
                              <Select
                                style={{ width: 220 }}
                                placeholder="Выберите заявителя"
                                value={row.requester_id}
                                onChange={(v) => updateRow(idx, { requester_id: v })}
                                options={requesterSelectOptions(row, data)}
                                showSearch
                                optionFilterProp="label"
                              />
                            </div>
                          </Space>
                          {pt?.default_company_payer ? (
                            <Typography.Text type="secondary">
                              В создаваемой заявке плательщик будет: «{pt.default_company_payer}» — задано в «Настройка
                              формы заявки» для типа «{row.payment_type}»
                            </Typography.Text>
                          ) : (
                            <Typography.Text type="secondary">
                              Для типа «{row.payment_type}» в «Настройка формы заявки» не задана компания-плательщик — в
                              заявке поле может остаться пустым.
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
                              onChange={(v) => {
                                updateRow(idx, { vendor_ref_id: v, contract_ref_id: null })
                                refreshContractsForIdx(idx, v ?? null, row.payment_type)
                              }}
                              options={vendorOpts}
                              allowClear
                              showSearch
                              optionFilterProp="label"
                            />
                          </div>
                          {pt?.contracts_required ? (
                            <div>
                              <Typography.Text strong style={labelBlockAboveField}>
                                Договор
                              </Typography.Text>
                              <Select
                                style={{ width: '100%' }}
                                placeholder={row.vendor_ref_id ? 'Выберите договор' : 'Сначала выберите поставщика'}
                                value={row.contract_ref_id ?? undefined}
                                onChange={(v) => updateRow(idx, { contract_ref_id: v })}
                                options={contractOptsMap[idx] ?? []}
                                allowClear
                                showSearch
                                optionFilterProp="label"
                              />
                            </div>
                          ) : null}
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
                      ),
                    },
                  ]}
                />
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
