import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Button, Col, DatePicker, Divider, Form, Input, InputNumber, Modal, Row, Select, Space, Switch, Typography } from 'antd'
import type { Dayjs } from 'dayjs'
import dayjs from 'dayjs'
import { listVendors, type RequestCategoryOption, type RequestFormOptionsPaymentType } from '../../lib/api'
import { generalFormPurposes, isCashRegisterTransferPurpose } from '../../lib/cashRegisterTransfer'
import { vendorKindForPaymentType } from '../../lib/requestPaymentTypes'
import { requestStatusLabel, requestStatusStep } from '../../lib/requestStatusLabels'
import { formatAmountInput, parseAmountInput } from '../useCashRegisterTransferForm'

export type RequestEditDraft = {
  title: string
  description: string
  amount: number | null
  currency: string
  status: string
  urgency: string
  payment_type: string
  category: string
  vendor: string
  vendorRefId: number | null
  payment_purpose: string
  expense_id: string
  billing_date: Dayjs | null
  requester: string
  amortization_enabled: boolean
  amortization_months: number
}

/** Поля заявки, из которых собирается черновик правки. */
export type RequestEditSource = {
  title?: string | null
  description?: string | null
  amount?: number | string | null
  currency?: string | null
  status?: string | null
  urgency?: string | null
  payment_type?: string | null
  category?: string | null
  vendor?: string | null
  vendor_ref?: number | null
  payment_purpose?: string | null
  expense_id?: string | null
  billing_date?: string | null
  requester?: number | null
  amortization_months?: number | null
}

type Option<V = string> = { label: string; value: V }
/** label — для показа (с ИНН), name — то, что пишется в заявку. */
type VendorOption = Option<number> & { name: string }

const REQUEST_CURRENCIES = ['UZS', 'USD', 'EUR', 'RUB'] as const
const REQUEST_URGENCIES = ['Низко', 'Обычно', 'Срочно'] as const
const AMORTIZATION_MONTHS = [2, 3, 4, 5, 6] as const

/** Статус для показа: «На согласовании · шаг 2», «Оплачена» и т. п. */
function requestStatusText(status: string): string {
  const step = requestStatusStep(status)
  if (step !== null) return `На согласовании · шаг ${step}`
  return status ? requestStatusLabel(status) : '—'
}

/** Значения справочника плюс текущее значение заявки, если его там нет (чтобы Select не показывал «пусто»). */
function withCurrent(values: readonly string[], current?: string | null): Option[] {
  const list = [...values]
  const cur = (current ?? '').trim()
  if (cur && !list.includes(cur)) list.push(cur)
  return list.map((value) => ({ value, label: value }))
}

export function requestEditDraftFromDetail(detail: RequestEditSource): RequestEditDraft {
  const months = Number(detail.amortization_months || 1)
  const amount = Number(detail.amount)
  return {
    title: detail.title || '',
    description: detail.description || '',
    amount: detail.amount != null && Number.isFinite(amount) ? amount : null,
    currency: detail.currency || 'UZS',
    status: detail.status || '',
    urgency: detail.urgency || '',
    payment_type: detail.payment_type || '',
    category: detail.category || '',
    vendor: detail.vendor || '',
    vendorRefId: detail.vendor_ref ?? null,
    payment_purpose: detail.payment_purpose || '',
    expense_id: (detail.expense_id || '').trim(),
    billing_date: detail.billing_date ? dayjs(detail.billing_date) : null,
    requester: detail.requester != null ? String(detail.requester) : '',
    amortization_enabled: months > 1,
    amortization_months: months > 1 ? months : 2,
  }
}

function draftSignature(draft: RequestEditDraft): string {
  // Сравниваем итоговые значения: включить и выключить амортизацию — не правка.
  const { amortization_enabled: _enabled, ...rest } = draft
  return JSON.stringify({
    ...rest,
    title: draft.title.trim(),
    description: draft.description.trim(),
    payment_purpose: draft.payment_purpose.trim(),
    expense_id: draft.expense_id.trim(),
    billing_date: draft.billing_date ? draft.billing_date.format('YYYY-MM') : null,
    amortization_months: draft.amortization_enabled ? draft.amortization_months : 1,
  })
}

type DraftErrors = Partial<Record<'title' | 'amount' | 'payment_purpose' | 'vendor', string>>

/** Обязательные поля — как в прежней форме правки: название, сумма, назначение (если настроено) и поставщик. */
function validateDraft(draft: RequestEditDraft, purposesConfigured: boolean): DraftErrors {
  const errors: DraftErrors = {}
  if (!draft.title.trim()) errors.title = 'Введите название заявки'
  if (draft.amount == null) errors.amount = 'Укажите сумму'
  if (purposesConfigured && !draft.payment_purpose.trim()) errors.payment_purpose = 'Выберите назначение платежа'
  if (!draft.vendor.trim()) errors.vendor = 'Укажите поставщика'
  return errors
}

export type RequestEditModalProps = {
  open: boolean
  requestId: number | null
  initialDraft: RequestEditDraft | null
  /** Настройки типов оплаты из form-options: назначения платежа и их категории. */
  paymentTypeConfigs: RequestFormOptionsPaymentType[]
  paymentTypeOptions: Option[]
  categoryOptions: RequestCategoryOption[]
  requesterOptions: Option[]
  saving: boolean
  onCancel: () => void
  onSave: (draft: RequestEditDraft) => void
}

export function RequestEditModal({
  open,
  requestId,
  initialDraft,
  paymentTypeConfigs,
  paymentTypeOptions,
  categoryOptions,
  requesterOptions,
  saving,
  onCancel,
  onSave,
}: RequestEditModalProps) {
  const [draft, setDraft] = useState<RequestEditDraft | null>(initialDraft)
  const [errors, setErrors] = useState<DraftErrors>({})
  const [vendorOptions, setVendorOptions] = useState<VendorOption[]>([])
  const [vendorLoading, setVendorLoading] = useState(false)
  const vendorSearchTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  // Номер последнего запроса поставщиков: ответы на устаревшие запросы отбрасываются.
  const vendorRequestRef = useRef(0)
  const [modal, modalContextHolder] = Modal.useModal()

  // Сброс черновика при открытии — во время рендера, а не в эффекте: иначе первый кадр и запрос поставщиков
  // шли бы по прошлой заявке.
  const [syncedWith, setSyncedWith] = useState<{ open: boolean; initialDraft: RequestEditDraft | null }>({
    open,
    initialDraft,
  })
  if (syncedWith.open !== open || (open && syncedWith.initialDraft !== initialDraft)) {
    setSyncedWith({ open, initialDraft })
    if (open) {
      setDraft(initialDraft)
      setErrors({})
    }
  }

  const patch = useCallback((next: Partial<RequestEditDraft>) => {
    setDraft((prev) => (prev ? { ...prev, ...next } : prev))
    setErrors((prev) => {
      const keys = Object.keys(next) as Array<keyof DraftErrors>
      if (!keys.some((k) => prev[k])) return prev
      const copy = { ...prev }
      for (const k of keys) delete copy[k]
      return copy
    })
  }, [])

  const paymentTypeConfig = useMemo(
    () => paymentTypeConfigs.find((p) => p.payment_type === draft?.payment_type) ?? null,
    [paymentTypeConfigs, draft?.payment_type],
  )

  const purposeOptions = useMemo(() => {
    const all = paymentTypeConfig?.payment_purposes ?? []
    // Перевод между кассами — только кнопкой перевода; у уже такой заявки значение оставляем.
    const keepTransfer = isCashRegisterTransferPurpose(draft?.payment_purpose)
    const visible = keepTransfer ? all : generalFormPurposes(all).purposes
    const options = visible.map((p) => ({ value: p.name, label: p.name, category: p.category }))
    const cur = draft?.payment_purpose?.trim()
    if (cur && !options.some((o) => o.value === cur)) {
      options.push({ value: cur, label: cur, category: draft?.category ?? '' })
    }
    return options
  }, [paymentTypeConfig, draft?.payment_purpose, draft?.category])
  const purposesConfigured = (paymentTypeConfig?.payment_purposes?.length ?? 0) > 0

  const categorySelectOptions = useMemo(
    () =>
      withCurrent(
        categoryOptions.map((c) => c.name).sort((a, b) => a.localeCompare(b)),
        draft?.category,
      ),
    [categoryOptions, draft?.category],
  )

  const paymentTypeSelectOptions = useMemo(() => {
    const cur = draft?.payment_type?.trim()
    if (!cur || paymentTypeOptions.some((o) => o.value === cur)) return paymentTypeOptions
    return [...paymentTypeOptions, { value: cur, label: cur }]
  }, [paymentTypeOptions, draft?.payment_type])

  const currencyOptions = useMemo(() => withCurrent(REQUEST_CURRENCIES, initialDraft?.currency), [initialDraft?.currency])
  const urgencyOptions = useMemo(() => withCurrent(REQUEST_URGENCIES, initialDraft?.urgency), [initialDraft?.urgency])

  const loadVendors = useCallback(async (paymentType: string, search: string) => {
    if (!paymentType) return
    const requestNo = ++vendorRequestRef.current
    setVendorLoading(true)
    try {
      const rows = await listVendors({ kind: vendorKindForPaymentType(paymentType), search })
      if (requestNo !== vendorRequestRef.current) return
      setVendorOptions(
        rows.map((r) => ({
          value: r.id,
          name: r.name,
          label: r.kind === 'transfer' && r.inn ? `${r.name} (ИНН ${r.inn})` : r.name,
        })),
      )
    } catch (e: unknown) {
      if (requestNo !== vendorRequestRef.current) return
      console.warn('request edit: vendors not loaded', e)
      setVendorOptions([])
    } finally {
      if (requestNo === vendorRequestRef.current) setVendorLoading(false)
    }
  }, [])

  useEffect(() => {
    // Отложенный поиск по прежнему типу оплаты больше не нужен.
    window.clearTimeout(vendorSearchTimerRef.current)
    if (open && draft?.payment_type) void loadVendors(draft.payment_type, '')
  }, [open, draft?.payment_type, loadVendors])

  useEffect(() => () => window.clearTimeout(vendorSearchTimerRef.current), [])

  const onVendorSearch = (value: string) => {
    window.clearTimeout(vendorSearchTimerRef.current)
    const paymentType = draft?.payment_type ?? ''
    vendorSearchTimerRef.current = setTimeout(() => void loadVendors(paymentType, value), 300)
  }

  const dirty = useMemo(
    () => Boolean(draft && initialDraft && draftSignature(draft) !== draftSignature(initialDraft)),
    [draft, initialDraft],
  )

  const requestClose = () => {
    if (saving) return
    if (!dirty) {
      onCancel()
      return
    }
    modal.confirm({
      title: 'Закрыть без сохранения?',
      content: 'Внесённые изменения будут потеряны.',
      okText: 'Закрыть',
      okButtonProps: { danger: true },
      cancelText: 'Продолжить правку',
      onOk: onCancel,
    })
  }

  const submit = () => {
    if (!draft || !dirty || saving) return
    const nextErrors = validateDraft(draft, purposesConfigured)
    setErrors(nextErrors)
    if (Object.keys(nextErrors).length > 0) return
    onSave(draft)
  }

  const onPaymentTypeChange = (value: string) => {
    if (!draft) return
    const purposes = paymentTypeConfigs.find((p) => p.payment_type === value)?.payment_purposes ?? []
    const next: Partial<RequestEditDraft> = { payment_type: value }
    if (purposes.length > 0) {
      const matched = purposes.find((p) => p.name === draft.payment_purpose)
      if (matched) next.category = matched.category
      else Object.assign(next, { payment_purpose: '', category: '' })
    }
    // Справочник поставщиков зависит от вида оплаты (перечисление / наличные / карта).
    if (vendorKindForPaymentType(value) !== vendorKindForPaymentType(draft.payment_type)) {
      Object.assign(next, { vendor: '', vendorRefId: null })
    }
    patch(next)
  }


  const item = (key: keyof DraftErrors) =>
    errors[key] ? { validateStatus: 'error' as const, help: errors[key] } : {}

  // Старые заявки хранят поставщика текстом без ссылки на справочник — показываем его как есть.
  const vendorValue = draft?.vendor
    ? { value: draft.vendorRefId ?? `text:${draft.vendor}`, label: draft.vendor }
    : undefined

  return (
    <>
      {modalContextHolder}
      <Modal
        open={open}
        title={requestId ? `Редактировать заявку #${requestId}` : 'Редактировать заявку'}
        width={760}
        onCancel={requestClose}
        maskClosable={!dirty}
        destroyOnClose
        styles={{ body: { maxHeight: 'calc(100dvh - 220px)', overflowY: 'auto', overflowX: 'hidden' } }}
        footer={
          <Space>
            <Button onClick={requestClose} disabled={saving}>
              Отмена
            </Button>
            <Button type="primary" loading={saving} disabled={!dirty} onClick={submit}>
              Сохранить
            </Button>
          </Space>
        }
      >
        {draft ? (
          <Form layout="vertical" requiredMark component="div">
            <Divider orientation="left" orientationMargin={0} plain style={{ marginTop: 8 }}>
              Основное
            </Divider>
            <Form.Item label="Название" htmlFor="request-edit-title" required {...item('title')}>
              <Input id="request-edit-title" value={draft.title} maxLength={200} onChange={(e) => patch({ title: e.target.value })} />
            </Form.Item>
            <Form.Item label="Описание" htmlFor="request-edit-description">
              <Input.TextArea
                id="request-edit-description"
                autoSize={{ minRows: 2, maxRows: 6 }}
                value={draft.description}
                onChange={(e) => patch({ description: e.target.value })}
              />
            </Form.Item>
            <Row gutter={16}>
              <Col xs={24} sm={12}>
                <Form.Item label="Сумма" htmlFor="request-edit-amount" required {...item('amount')}>
                  <Space.Compact style={{ width: '100%' }}>
                    <InputNumber<string>
                      id="request-edit-amount"
                      style={{ flex: 1, minWidth: 0 }}
                      min="0"
                      stringMode
                      inputMode="decimal"
                      value={draft.amount == null ? undefined : String(draft.amount)}
                      formatter={formatAmountInput}
                      parser={parseAmountInput}
                      onChange={(value) => {
                        const n = value == null || value === '' ? null : Number(value)
                        patch({ amount: n != null && Number.isFinite(n) ? n : null })
                      }}
                    />
                    <Select
                      style={{ width: 96 }}
                      aria-label="Валюта"
                      value={draft.currency}
                      onChange={(value) => patch({ currency: value })}
                      options={currencyOptions}
                    />
                  </Space.Compact>
                </Form.Item>
              </Col>
              <Col xs={24} sm={12}>
                <Form.Item
                  label="Статус"
                  htmlFor="request-edit-status"
                  extra="Меняется только через согласование"
                >
                  <Input id="request-edit-status" value={requestStatusText(draft.status)} disabled />
                </Form.Item>
              </Col>
            </Row>
            <Row gutter={16}>
              <Col xs={24} sm={12}>
                <Form.Item label="Срочность" htmlFor="request-edit-urgency">
                  <Select
                    id="request-edit-urgency"
                    placeholder="Выберите"
                    value={draft.urgency || undefined}
                    onChange={(value) => patch({ urgency: value })}
                    options={urgencyOptions}
                  />
                </Form.Item>
              </Col>
              <Col xs={24} sm={12}>
                <Form.Item label="Заявитель" htmlFor="request-edit-requester">
                  <Select
                    id="request-edit-requester"
                    placeholder="Выберите"
                    value={draft.requester || undefined}
                    onChange={(value) => patch({ requester: value ?? '' })}
                    options={requesterOptions}
                    allowClear
                    showSearch
                    optionFilterProp="label"
                  />
                </Form.Item>
              </Col>
            </Row>

            <Divider orientation="left" orientationMargin={0} plain>
              Оплата
            </Divider>
            <Row gutter={16}>
              <Col xs={24} sm={12}>
                <Form.Item label="Тип оплаты" htmlFor="request-edit-payment-type">
                  <Select
                    id="request-edit-payment-type"
                    placeholder="Выберите"
                    value={draft.payment_type || undefined}
                    onChange={onPaymentTypeChange}
                    options={paymentTypeSelectOptions}
                    showSearch
                    optionFilterProp="label"
                  />
                </Form.Item>
              </Col>
              <Col xs={24} sm={12}>
                <Form.Item
                  label="Поставщик"
                  htmlFor="request-edit-vendor"
                  required
                  {...item('vendor')}
                  extra={
                    !errors.vendor && draft.vendor && draft.vendorRefId == null
                      ? 'Поставщик не привязан к справочнику'
                      : undefined
                  }
                >
                  <Select<{ value: number | string; label: string } | undefined>
                    id="request-edit-vendor"
                    placeholder={draft.payment_type ? 'Начните вводить название или ИНН' : 'Сначала выберите тип оплаты'}
                    disabled={!draft.payment_type}
                    labelInValue
                    value={vendorValue}
                    onChange={(selected) => {
                      const option = vendorOptions.find((o) => o.value === selected?.value)
                      if (!option) patch({ vendorRefId: null, vendor: '' })
                      else patch({ vendorRefId: option.value, vendor: option.name })
                    }}
                    options={vendorOptions}
                    onSearch={onVendorSearch}
                    loading={vendorLoading}
                    filterOption={false}
                    showSearch
                    allowClear
                    notFoundContent={vendorLoading ? 'Поиск…' : 'Не найдено'}
                  />
                </Form.Item>
              </Col>
            </Row>
            <Row gutter={16}>
              <Col xs={24} sm={12}>
                {purposesConfigured ? (
                  <Form.Item
                    label="Назначение платежа"
                    htmlFor="request-edit-purpose"
                    required
                    {...item('payment_purpose')}
                  >
                    <Select
                      id="request-edit-purpose"
                      placeholder="Выберите назначение"
                      value={draft.payment_purpose || undefined}
                      onChange={(name: string) => {
                        const matched = purposeOptions.find((o) => o.value === name)
                        patch({ payment_purpose: name, category: matched?.category ?? '' })
                      }}
                      options={purposeOptions}
                      showSearch
                      optionFilterProp="label"
                    />
                  </Form.Item>
                ) : (
                  <Form.Item label="Назначение платежа" htmlFor="request-edit-purpose">
                    <Input
                      id="request-edit-purpose"
                      value={draft.payment_purpose}
                      onChange={(e) => patch({ payment_purpose: e.target.value })}
                    />
                  </Form.Item>
                )}
              </Col>
              <Col xs={24} sm={12}>
                <Form.Item
                  label="Категория"
                  htmlFor="request-edit-category"
                  extra={purposesConfigured ? 'Подставляется из назначения платежа' : undefined}
                >
                  <Select
                    id="request-edit-category"
                    placeholder="Выберите"
                    value={draft.category || undefined}
                    onChange={(value) => patch({ category: value ?? '' })}
                    options={categorySelectOptions}
                    disabled={purposesConfigured}
                    showSearch
                    optionFilterProp="label"
                  />
                </Form.Item>
              </Col>
            </Row>

            <Divider orientation="left" orientationMargin={0} plain>
              Учёт
            </Divider>
            <Row gutter={16}>
              <Col xs={24} sm={12}>
                <Form.Item label="Дата биллинга" htmlFor="request-edit-billing-date">
                  <DatePicker
                    id="request-edit-billing-date"
                    picker="month"
                    format="MM.YYYY"
                    placeholder="ММ.ГГГГ"
                    style={{ width: '100%' }}
                    value={draft.billing_date}
                    onChange={(value) => patch({ billing_date: value })}
                    // Очистка даты на сервер не уходит, поэтому её не предлагаем.
                    allowClear={false}
                    inputReadOnly
                  />
                </Form.Item>
              </Col>
              <Col xs={24} sm={12}>
                <Form.Item label="ID связанного расхода" htmlFor="request-edit-expense-id" extra="Номер расхода или документа банка/кассы">
                  <Input
                    id="request-edit-expense-id"
                    allowClear
                    value={draft.expense_id}
                    onChange={(e) => patch({ expense_id: e.target.value })}
                  />
                </Form.Item>
              </Col>
            </Row>
            <Form.Item label="Амортизация" htmlFor="request-edit-amortization" style={{ marginBottom: 0 }}>
              <Space wrap align="center">
                <Switch
                  id="request-edit-amortization"
                  checked={draft.amortization_enabled}
                  onChange={(checked) =>
                    patch({
                      amortization_enabled: checked,
                      amortization_months: checked ? draft.amortization_months : 2,
                    })
                  }
                />
                {draft.amortization_enabled ? (
                  <Select
                    style={{ width: 140 }}
                    aria-label="Срок амортизации"
                    value={draft.amortization_months}
                    onChange={(value) => patch({ amortization_months: value })}
                    options={AMORTIZATION_MONTHS.map((m) => ({ value: m, label: `${m} мес.` }))}
                  />
                ) : (
                  <Typography.Text type="secondary">Расход учитывается целиком в месяце биллинга</Typography.Text>
                )}
              </Space>
            </Form.Item>
          </Form>
        ) : null}
      </Modal>
    </>
  )
}
