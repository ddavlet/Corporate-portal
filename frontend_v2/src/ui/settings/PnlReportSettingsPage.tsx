import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Input, Select, Space, Typography, message } from 'antd'
import {
  getRequestFormOptions,
  getSettingsAccess,
  getTenantReportSettings,
  patchTenantReportSettings,
  type PnlReportSettingsSnapshot,
  type RequestFormOptionsPaymentType,
} from '../../lib/api'

function splitList(text: string): string[] {
  return text
    .split(/[\n,]+/)
    .map((s) => s.trim())
    .filter(Boolean)
}

function joinList(items: string[] | undefined): string {
  return (items ?? []).join('\n')
}

function collectActivePurposeOptions(paymentTypes: RequestFormOptionsPaymentType[]): { value: string; label: string }[] {
  const byName = new Map<string, string>()
  for (const pt of paymentTypes) {
    for (const p of pt.payment_purposes || []) {
      const name = String(p.name || '').trim()
      if (!name) continue
      const cat = String(p.category || '').trim()
      const label = cat ? `${name} → ${cat}` : name
      if (!byName.has(name)) byName.set(name, label)
    }
  }
  return [...byName.entries()]
    .sort((a, b) => a[0].localeCompare(b[0], 'ru'))
    .map(([value, label]) => ({ value, label }))
}

/** Совпадает с InvestReturn.type в backend_v2 (apps.modules.investments.models). */
const INVEST_RETURN_TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: 'дивиденды', label: 'Дивиденды' },
  { value: 'проценты', label: 'Проценты' },
  { value: 'доля_прибыли', label: 'Доля прибыли' },
  { value: 'тело_инвестиций', label: 'Тело инвестиций' },
  /** Иногда встречается в старых данных / n8n */
  { value: 'Возврат', label: 'Возврат (устаревшее значение)' },
]

function categoriesFromFormSet(paymentTypes: RequestFormOptionsPaymentType[]): Set<string> {
  const s = new Set<string>()
  for (const pt of paymentTypes) {
    for (const p of pt.payment_purposes || []) {
      const c = String(p.category || '').trim()
      if (c) s.add(c)
    }
  }
  return s
}

/** Все назначения с данной категорией (имена совпадают с формой заявки). */
function purposeNamesMatchingCategories(
  categories: string[],
  paymentTypes: RequestFormOptionsPaymentType[],
): string[] {
  const catSet = new Set(categories.map((c) => c.trim()).filter(Boolean))
  const names: string[] = []
  for (const pt of paymentTypes) {
    for (const p of pt.payment_purposes || []) {
      const c = String(p.category || '').trim()
      const n = String(p.name || '').trim()
      if (!n || !c || !catSet.has(c)) continue
      names.push(n)
    }
  }
  return [...new Set(names)].sort((a, b) => a.localeCompare(b, 'ru'))
}

function purposeNameToCategory(name: string, paymentTypes: RequestFormOptionsPaymentType[]): string | null {
  const n = name.trim()
  for (const pt of paymentTypes) {
    for (const p of pt.payment_purposes || []) {
      if (String(p.name || '').trim() !== n) continue
      const c = String(p.category || '').trim()
      return c || null
    }
  }
  return null
}

function categoriesFromSelectedPurposeNames(
  purposeNames: string[],
  paymentTypes: RequestFormOptionsPaymentType[],
): string[] {
  const cats = new Set<string>()
  for (const name of purposeNames) {
    const c = purposeNameToCategory(name, paymentTypes)
    if (c) cats.add(c)
  }
  return [...cats].sort((a, b) => a.localeCompare(b, 'ru'))
}

function mergeSelectOptions(
  base: { value: string; label: string }[],
  selectedValues: string[],
): { value: string; label: string }[] {
  const known = new Set(base.map((o) => o.value))
  const extras = selectedValues.filter((v) => v && !known.has(v)).map((value) => ({
    value,
    label: `${value} (нет в справочнике)`,
  }))
  const merged = [...base, ...extras]
  merged.sort((a, b) => a.value.localeCompare(b.value, 'ru'))
  return merged
}

function normalizeStringList(raw: unknown): string[] {
  if (!Array.isArray(raw)) return []
  return raw.map((x) => String(x || '').trim()).filter(Boolean)
}

function buildConfigFromForm(fields: {
  startMonth: string
  incomeTaxPurpose: string
  cashExclude: string
  requestExcludeCategories: string[]
  investExcludeTypes: string[]
}): PnlReportSettingsSnapshot {
  return {
    start_month: fields.startMonth.trim(),
    income_tax_payment_purpose: fields.incomeTaxPurpose.trim(),
    cash_exclude_operations: splitList(fields.cashExclude),
    request_exclude_categories: [...fields.requestExcludeCategories],
    invest_return_exclude_types: [...fields.investExcludeTypes],
  }
}

export function PnlReportSettingsPage() {
  const [gateLoading, setGateLoading] = useState(true)
  const [allowed, setAllowed] = useState(false)
  const [gateError, setGateError] = useState<string | null>(null)

  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [paymentTypesFromForm, setPaymentTypesFromForm] = useState<RequestFormOptionsPaymentType[]>([])

  const [pnlSource, setPnlSource] = useState<'n8n' | 'backend'>('n8n')
  const [startMonth, setStartMonth] = useState('')
  const [incomeTaxPurpose, setIncomeTaxPurpose] = useState('')
  const [cashExclude, setCashExclude] = useState('')
  /** Назначения из формы заявки; в конфиг уходит производная по категориям. */
  const [requestExcludePurposeNames, setRequestExcludePurposeNames] = useState<string[]>([])
  /** Категории из сохранённого конфига, которых нет ни у одного активного назначения в форме. */
  const [legacyExcludeCategories, setLegacyExcludeCategories] = useState<string[]>([])
  const [serverRequestExcludeCategories, setServerRequestExcludeCategories] = useState<string[]>([])
  const [investExcludeTypes, setInvestExcludeTypes] = useState<string[]>([])
  const [updatedAt, setUpdatedAt] = useState<string | null>(null)

  const applyServerRow = useCallback((data: {
    pnl_source: 'n8n' | 'backend'
    pnl_config: PnlReportSettingsSnapshot
    updated_at?: string | null
  }) => {
    setPnlSource(data.pnl_source)
    const c = data.pnl_config ?? {}
    setStartMonth((c.start_month ?? '').trim())
    setIncomeTaxPurpose((c.income_tax_payment_purpose ?? '').trim())
    setCashExclude(joinList(c.cash_exclude_operations))
    setServerRequestExcludeCategories(normalizeStringList(c.request_exclude_categories))
    setInvestExcludeTypes(normalizeStringList(c.invest_return_exclude_types))
    setUpdatedAt(typeof data.updated_at === 'string' ? data.updated_at : null)
  }, [])

  useEffect(() => {
    let cancelled = false
    void (async () => {
      setGateLoading(true)
      setGateError(null)
      try {
        const access = await getSettingsAccess()
        if (cancelled) return
        setAllowed(Boolean(access.can_manage_tenant_settings))
      } catch (e: unknown) {
        if (cancelled) return
        setGateError(e instanceof Error ? e.message : 'Не удалось проверить доступ')
        setAllowed(false)
      } finally {
        if (!cancelled) setGateLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const incomePurposeOptions = useMemo(
    () => collectActivePurposeOptions(paymentTypesFromForm),
    [paymentTypesFromForm],
  )

  const allowedPurposeNames = useMemo(() => new Set(incomePurposeOptions.map((o) => o.value)), [incomePurposeOptions])

  useEffect(() => {
    const saved = serverRequestExcludeCategories
    if (!paymentTypesFromForm.length) {
      setRequestExcludePurposeNames([])
      setLegacyExcludeCategories(saved)
      return
    }
    const formCatSet = categoriesFromFormSet(paymentTypesFromForm)
    const legacy = saved.filter((c) => !formCatSet.has(c))
    const mappedCats = saved.filter((c) => formCatSet.has(c))
    setLegacyExcludeCategories(legacy)
    setRequestExcludePurposeNames(purposeNamesMatchingCategories(mappedCats, paymentTypesFromForm))
  }, [paymentTypesFromForm, serverRequestExcludeCategories])

  const requestExcludePurposeSelectOptions = useMemo(
    () => mergeSelectOptions(incomePurposeOptions, requestExcludePurposeNames),
    [incomePurposeOptions, requestExcludePurposeNames],
  )

  const resolvedRequestExcludeCategories = useMemo(() => {
    const fromPurposes = categoriesFromSelectedPurposeNames(requestExcludePurposeNames, paymentTypesFromForm)
    return [...new Set([...fromPurposes, ...legacyExcludeCategories])].sort((a, b) => a.localeCompare(b, 'ru'))
  }, [requestExcludePurposeNames, paymentTypesFromForm, legacyExcludeCategories])

  const investTypeSelectOptions = useMemo(
    () => mergeSelectOptions(INVEST_RETURN_TYPE_OPTIONS, investExcludeTypes),
    [investExcludeTypes],
  )

  const incomePurposeOrphan = useMemo(() => {
    const t = incomeTaxPurpose.trim()
    if (!t || incomePurposeOptions.length === 0) return null
    return allowedPurposeNames.has(t) ? null : t
  }, [incomeTaxPurpose, incomePurposeOptions.length, allowedPurposeNames])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [data, formOpts] = await Promise.all([getTenantReportSettings(), getRequestFormOptions()])
      applyServerRow(data)
      setPaymentTypesFromForm(formOpts.payment_types ?? [])
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Не удалось загрузить настройки')
    } finally {
      setLoading(false)
    }
  }, [applyServerRow])

  useEffect(() => {
    if (!allowed) return
    void load()
  }, [allowed, load])

  const onSave = async () => {
    setSaving(true)
    setError(null)
    try {
      const tax = incomeTaxPurpose.trim()
      if (pnlSource === 'backend' && incomePurposeOptions.length > 0) {
        if (!tax) {
          message.warning('Выберите назначение для подоходного налога из списка')
          setSaving(false)
          return
        }
        if (!allowedPurposeNames.has(tax)) {
          message.warning('Назначение должно быть одним из активных в настройках формы заявки')
          setSaving(false)
          return
        }
      }

      const pnl_config = buildConfigFromForm({
        startMonth,
        incomeTaxPurpose,
        cashExclude,
        requestExcludeCategories: resolvedRequestExcludeCategories,
        investExcludeTypes,
      })
      const data = await patchTenantReportSettings({ pnl_source: pnlSource, pnl_config })
      applyServerRow(data)
      message.success('Настройки PnL сохранены')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Не удалось сохранить')
    } finally {
      setSaving(false)
    }
  }

  const backendHint = useMemo(
    () =>
      pnlSource === 'backend'
        ? 'Для расчёта в приложении нужны все поля: месяц старта (YYYY-MM), списки фильтров и шаблон назначения для налога.'
        : null,
    [pnlSource],
  )

  if (gateLoading) {
    return <Card loading style={{ maxWidth: 720 }} />
  }
  if (!allowed) {
    return (
      <Alert
        type="warning"
        showIcon
        message="Доступ ограничен"
        description={
          gateError ??
          'Изменение настроек PnL доступно только администратору компании (роль admin).'
        }
      />
    )
  }

  return (
    <div style={{ maxWidth: 720 }}>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Отчёт PnL — источник данных
      </Typography.Title>
      <Typography.Paragraph type="secondary">
        Выбор между workflow в n8n и расчётом на сервере. Параметры ниже используются только при источнике
        «Расчёт в приложении».
      </Typography.Paragraph>

      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} /> : null}
      {backendHint ? <Alert type="info" showIcon message={backendHint} style={{ marginBottom: 16 }} /> : null}

      <Card loading={loading}>
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <div>
            <Typography.Text strong>Источник PnL</Typography.Text>
            <Select<'n8n' | 'backend'>
              style={{ width: '100%', marginTop: 8 }}
              value={pnlSource}
              onChange={setPnlSource}
              options={[
                { value: 'n8n', label: 'n8n (как настроено в автоматизации)' },
                { value: 'backend', label: 'Расчёт в приложении (backend)' },
              ]}
            />
          </div>

          <div>
            <Typography.Text strong>Стартовый месяц периода</Typography.Text>
            <Input
              style={{ marginTop: 8 }}
              placeholder="YYYY-MM, например 2026-01"
              value={startMonth}
              onChange={(e) => setStartMonth(e.target.value)}
            />
          </div>

          <div>
            <Typography.Text strong>Назначение платежа (подоходный налог)</Typography.Text>
            <Typography.Paragraph type="secondary" style={{ margin: '6px 0 0' }}>
              Только активные назначения из «Настройки → Заявки — форма создания» (совпадает с полем payment_purpose у
              заявки). Так backend сопоставляет строку с оплаченными заявками.
            </Typography.Paragraph>
            {incomePurposeOrphan ? (
              <Alert
                type="warning"
                showIcon
                style={{ marginTop: 8 }}
                message="В конфиге сохранено значение вне списка активных назначений"
                description={`Сейчас в данных: «${incomePurposeOrphan}». Выберите актуальное назначение из списка ниже.`}
              />
            ) : null}
            {incomePurposeOptions.length > 0 ? (
              <Select
                style={{ width: '100%', marginTop: 8 }}
                placeholder="Выберите назначение"
                value={allowedPurposeNames.has(incomeTaxPurpose.trim()) ? incomeTaxPurpose.trim() : undefined}
                onChange={(v) => setIncomeTaxPurpose(v)}
                options={incomePurposeOptions}
                showSearch
                optionFilterProp="label"
                allowClear
              />
            ) : (
              <>
                <Alert
                  type="info"
                  showIcon
                  style={{ marginTop: 8 }}
                  message="Нет активных назначений в форме заявки"
                  description="Добавьте назначения платежа для типов оплаты в настройках формы или введите текст вручную (для режима backend после появления списка выберите значение из него)."
                />
                <Input
                  style={{ marginTop: 8 }}
                  placeholder="Текст назначения (как в заявке / выписке)"
                  value={incomeTaxPurpose}
                  onChange={(e) => setIncomeTaxPurpose(e.target.value)}
                />
              </>
            )}
          </div>

          <div>
            <Typography.Text strong>Исключить операции кассы (подписи операций)</Typography.Text>
            <Typography.Paragraph type="secondary" style={{ margin: '6px 0 0' }}>
              Подпись операции как в кассовых поступлениях (поле operation / payload). Общего справочника нет — список
              вводится текстом.
            </Typography.Paragraph>
            <Input.TextArea
              style={{ marginTop: 8 }}
              rows={3}
              placeholder="По одному значению на строку"
              value={cashExclude}
              onChange={(e) => setCashExclude(e.target.value)}
            />
          </div>

          <div>
            <Typography.Text strong>Исключить заявки по назначению платежа</Typography.Text>
            <Typography.Paragraph type="secondary" style={{ margin: '6px 0 0' }}>
              В заявке категория подставляется автоматически из выбранного назначения. Здесь вы отмечаете назначения из
              формы — в отчёт не попадут заявки с соответствующими категориями (в конфиг сохраняются именно категории,
              как ожидает backend).
            </Typography.Paragraph>
            {legacyExcludeCategories.length > 0 ? (
              <Alert
                type="info"
                showIcon
                style={{ marginTop: 8 }}
                message="В конфиге есть категории без совпадения в текущей форме заявки"
                description={`Они сохранятся при следующем сохранении: ${legacyExcludeCategories.join(', ')}.`}
              />
            ) : null}
            {incomePurposeOptions.length > 0 ? (
              <>
                <Select
                  mode="multiple"
                  allowClear
                  showSearch
                  optionFilterProp="label"
                  placeholder="Выберите назначения, заявки с их категориями исключить из PnL"
                  style={{ width: '100%', marginTop: 8 }}
                  value={requestExcludePurposeNames}
                  onChange={(v) => setRequestExcludePurposeNames(v)}
                  options={requestExcludePurposeSelectOptions}
                  maxTagCount="responsive"
                />
                {resolvedRequestExcludeCategories.length > 0 ? (
                  <Typography.Paragraph type="secondary" style={{ margin: '8px 0 0', fontSize: 13 }}>
                    Итоговые категории в конфиге: {resolvedRequestExcludeCategories.join(', ')}
                  </Typography.Paragraph>
                ) : (
                  <Typography.Paragraph type="secondary" style={{ margin: '8px 0 0', fontSize: 13 }}>
                    Категории для исключения не выбраны.
                  </Typography.Paragraph>
                )}
              </>
            ) : (
              <Input.TextArea
                style={{ marginTop: 8 }}
                rows={3}
                placeholder="Нет активных назначений в форме — категории по строке на значение"
                value={joinList(serverRequestExcludeCategories)}
                onChange={(e) => setServerRequestExcludeCategories(splitList(e.target.value))}
              />
            )}
          </div>

          <div>
            <Typography.Text strong>Исключить типы выплат по инвестициям</Typography.Text>
            <Typography.Paragraph type="secondary" style={{ margin: '6px 0 0' }}>
              Значения поля type у записей invest_returns (как в модуле инвестиций). Дополнительные строки из конфига
              остаются доступными для выбора.
            </Typography.Paragraph>
            <Select
              mode="multiple"
              allowClear
              showSearch
              optionFilterProp="label"
              placeholder="Выберите типы"
              style={{ width: '100%', marginTop: 8 }}
              value={investExcludeTypes}
              onChange={(v) => setInvestExcludeTypes(v)}
              options={investTypeSelectOptions}
              maxTagCount="responsive"
            />
          </div>

          <Button type="primary" onClick={() => void onSave()} loading={saving}>
            Сохранить
          </Button>

          {updatedAt ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              Обновлено: {updatedAt}
            </Typography.Text>
          ) : null}
        </Space>
      </Card>
    </div>
  )
}
