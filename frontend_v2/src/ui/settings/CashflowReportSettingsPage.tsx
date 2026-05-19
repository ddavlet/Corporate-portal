import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Input, Select, Space, Tag, Typography, message } from 'antd'
import {
  getSettingsAccess,
  getTenantPnlPaymentPurposePool,
  getTenantCashflowReportSettings,
  patchTenantCashflowReportSettings,
  type CashflowDiagnosticsItem,
  type CashflowReportSettingsSnapshot,
} from '../../lib/api'

const REQUEST_PAYMENT_OPTIONS = [
  { value: 'Наличные', label: 'Наличные' },
  { value: 'Перечисление', label: 'Перечисление' },
  { value: 'Пополнение', label: 'Пополнение' },
  { value: 'Платежная карта', label: 'Платежная карта' },
] as const

const INVEST_RETURN_TYPES = [
  { value: 'дивиденды', label: 'Дивиденды' },
  { value: 'проценты', label: 'Проценты' },
  { value: 'доля_прибыли', label: 'Доля прибыли' },
  { value: 'тело_инвестиций', label: 'Тело инвестиций' },
] as const

type InvestBucket = 'operational' | 'other' | 'invest_returns'

function splitList(text: string): string[] {
  return text
    .split(/[\n,]+/)
    .map((s) => s.trim())
    .filter(Boolean)
}

function joinList(items: string[] | undefined): string {
  return (items ?? []).join('\n')
}

function uniqTrimmedStrings(items: Iterable<string>): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const x of items) {
    const s = String(x ?? '').trim()
    if (!s || seen.has(s)) continue
    seen.add(s)
    out.push(s)
  }
  return out
}

function hasFullInvestPartition(c: CashflowReportSettingsSnapshot): boolean {
  const a = new Set([...(c.invest_return_type_operational ?? []), ...(c.invest_return_type_other ?? []), ...(c.invest_return_type_invest_returns ?? [])])
  return INVEST_RETURN_TYPES.every((t) => a.has(t.value))
}

function investBucketsFromConfig(c: CashflowReportSettingsSnapshot): Record<string, InvestBucket> {
  const out: Record<string, InvestBucket> = {}
  for (const t of INVEST_RETURN_TYPES) {
    if ((c.invest_return_type_operational ?? []).includes(t.value)) out[t.value] = 'operational'
    else if ((c.invest_return_type_other ?? []).includes(t.value)) out[t.value] = 'other'
    else if ((c.invest_return_type_invest_returns ?? []).includes(t.value)) out[t.value] = 'invest_returns'
    else out[t.value] = 'operational'
  }
  return out
}

/** Valid partition used only when saved config has no invest partition yet (form defaults). */
function defaultInvestBuckets(): Record<string, InvestBucket> {
  return {
    дивиденды: 'invest_returns',
    проценты: 'operational',
    доля_прибыли: 'operational',
    тело_инвестиций: 'other',
  }
}

function buildConfigFromForm(fields: {
  startMonth: string
  cashExclude: string
  requestExclude: string
  requestPaymentTypes: string[]
  purposeOperational: string[]
  purposeOther: string[]
  purposeInvestReturns: string[]
  investBucketByType: Record<string, InvestBucket>
}): CashflowReportSettingsSnapshot {
  const op = uniqTrimmedStrings(fields.purposeOperational)
  const ot = uniqTrimmedStrings(fields.purposeOther)
  const inv = uniqTrimmedStrings(fields.purposeInvestReturns)
  const operational: string[] = []
  const other: string[] = []
  const investReturns: string[] = []
  for (const t of INVEST_RETURN_TYPES) {
    const b = fields.investBucketByType[t.value] ?? 'operational'
    if (b === 'operational') operational.push(t.value)
    else if (b === 'other') other.push(t.value)
    else investReturns.push(t.value)
  }
  return {
    start_month: fields.startMonth.trim(),
    cash_exclude_operations: splitList(fields.cashExclude),
    request_exclude_categories: splitList(fields.requestExclude),
    request_payment_types_for_pnl: [...fields.requestPaymentTypes],
    payment_purpose_operational: op,
    payment_purpose_other: ot,
    payment_purpose_invest_returns: inv,
    invest_return_type_operational: operational,
    invest_return_type_other: other,
    invest_return_type_invest_returns: investReturns,
  }
}

export function CashflowReportSettingsPage() {
  const [gateLoading, setGateLoading] = useState(true)
  const [allowed, setAllowed] = useState(false)
  const [gateError, setGateError] = useState<string | null>(null)

  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [cashflowSource, setCashflowSource] = useState<'n8n' | 'backend'>('n8n')
  const [startMonth, setStartMonth] = useState('')
  const [cashExclude, setCashExclude] = useState('')
  const [requestExclude, setRequestExclude] = useState('')
  const [requestPaymentTypes, setRequestPaymentTypes] = useState<string[]>([])
  const [purposeOperational, setPurposeOperational] = useState<string[]>([])
  const [purposeOther, setPurposeOther] = useState<string[]>([])
  const [purposeInvestReturns, setPurposeInvestReturns] = useState<string[]>([])
  const [rawPurposePool, setRawPurposePool] = useState<string[]>([])
  const [purposePoolLoadError, setPurposePoolLoadError] = useState<string | null>(null)
  const [investBucketByType, setInvestBucketByType] = useState<Record<string, InvestBucket>>(() =>
    defaultInvestBuckets(),
  )
  const [updatedAt, setUpdatedAt] = useState<string | null>(null)
  const [diagnostics, setDiagnostics] = useState<CashflowDiagnosticsItem[] | null>(null)
  const [diagnosticsError, setDiagnosticsError] = useState<string | null>(null)

  const applyServerRow = useCallback(
    (data: {
      cashflow_source: 'n8n' | 'backend'
      cashflow_config: CashflowReportSettingsSnapshot
      updated_at?: string | null
      cashflow_diagnostics?: { unassigned_payment_purposes?: CashflowDiagnosticsItem[]; error?: string }
    }) => {
      setCashflowSource(data.cashflow_source)
      const c = data.cashflow_config ?? {}
      setStartMonth((c.start_month ?? '').trim())
      setCashExclude(joinList(c.cash_exclude_operations))
      setRequestExclude(joinList(c.request_exclude_categories))
      setRequestPaymentTypes([...(c.request_payment_types_for_pnl ?? [])])
      setPurposeOperational(uniqTrimmedStrings(c.payment_purpose_operational ?? []))
      setPurposeOther(uniqTrimmedStrings(c.payment_purpose_other ?? []))
      setPurposeInvestReturns(uniqTrimmedStrings(c.payment_purpose_invest_returns ?? []))
      setInvestBucketByType(hasFullInvestPartition(c) ? investBucketsFromConfig(c) : defaultInvestBuckets())
      setUpdatedAt(typeof data.updated_at === 'string' ? data.updated_at : null)
      if (data.cashflow_diagnostics?.error) {
        setDiagnosticsError(data.cashflow_diagnostics.error)
        setDiagnostics(null)
      } else if (data.cashflow_diagnostics?.unassigned_payment_purposes) {
        setDiagnosticsError(null)
        setDiagnostics(data.cashflow_diagnostics.unassigned_payment_purposes)
      } else {
        setDiagnosticsError(null)
        setDiagnostics(null)
      }
    },
    [],
  )

  const loadDiagnostics = useCallback(async () => {
    if (cashflowSource !== 'backend') {
      setDiagnostics(null)
      setDiagnosticsError(null)
      return
    }
    try {
      const data = await getTenantCashflowReportSettings({ cashflowDiagnostics: true })
      if (data.cashflow_diagnostics?.error) {
        setDiagnosticsError(data.cashflow_diagnostics.error)
        setDiagnostics(null)
      } else {
        setDiagnosticsError(null)
        setDiagnostics(data.cashflow_diagnostics?.unassigned_payment_purposes ?? [])
      }
    } catch {
      setDiagnosticsError(null)
      setDiagnostics(null)
    }
  }, [cashflowSource])

  const diagnosticPurposeStrings = useMemo(
    () => uniqTrimmedStrings((diagnostics ?? []).map((d) => String(d.purpose ?? ''))),
    [diagnostics],
  )

  const diagnosticPurposeSet = useMemo(
    () => new Set((diagnostics ?? []).map((d) => d.purpose)),
    [diagnostics],
  )

  const fullPurposeOptions = useMemo(() => {
    const s = new Set<string>()
    for (const x of rawPurposePool) {
      const t = x.trim()
      if (t) s.add(t)
    }
    for (const x of diagnosticPurposeStrings) {
      if (x) s.add(x)
    }
    for (const x of [...purposeOperational, ...purposeOther, ...purposeInvestReturns]) {
      const t = x.trim()
      if (t) s.add(t)
    }
    return [...s].sort((a, b) => a.localeCompare(b, 'ru'))
  }, [rawPurposePool, diagnosticPurposeStrings, purposeOperational, purposeOther, purposeInvestReturns])

  const purposeSelectOptions = useMemo(
    () => fullPurposeOptions.map((value) => ({ value, label: value })),
    [fullPurposeOptions],
  )

  const assignedPurposeSet = useMemo(
    () => new Set([...purposeOperational, ...purposeOther, ...purposeInvestReturns]),
    [purposeOperational, purposeOther, purposeInvestReturns],
  )

  const unassignedFromPaidRequests = useMemo(() => {
    if (!diagnostics?.length) return []
    return diagnostics.filter((d) => !assignedPurposeSet.has(d.purpose))
  }, [diagnostics, assignedPurposeSet])

  const unassignedFromPoolOnly = useMemo(
    () => fullPurposeOptions.filter((p) => !assignedPurposeSet.has(p) && !diagnosticPurposeSet.has(p)),
    [fullPurposeOptions, assignedPurposeSet, diagnosticPurposeSet],
  )

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

  const refetchPurposePool = useCallback(async (types: string[]) => {
    setPurposePoolLoadError(null)
    try {
      const pool = await getTenantPnlPaymentPurposePool({ forPnlPaymentTypes: types })
      setRawPurposePool(pool.purposes)
    } catch (poolErr: unknown) {
      setPurposePoolLoadError(
        poolErr instanceof Error ? poolErr.message : 'Не удалось обновить список назначений',
      )
    }
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getTenantCashflowReportSettings()
      applyServerRow(data)
      let typesForPool = [...(data.cashflow_config?.request_payment_types_for_pnl ?? [])]
      if (data.cashflow_source === 'backend') {
        const withDiag = await getTenantCashflowReportSettings({ cashflowDiagnostics: true })
        applyServerRow(withDiag)
        typesForPool = [...(withDiag.cashflow_config?.request_payment_types_for_pnl ?? [])]
      } else {
        setDiagnostics(null)
        setDiagnosticsError(null)
      }
      await refetchPurposePool(typesForPool)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Не удалось загрузить настройки')
    } finally {
      setLoading(false)
    }
  }, [applyServerRow, refetchPurposePool])

  useEffect(() => {
    if (!allowed) return
    void load()
  }, [allowed, load])

  const onSave = async () => {
    setSaving(true)
    setError(null)
    try {
      const cashflow_config = buildConfigFromForm({
        startMonth,
        cashExclude,
        requestExclude,
        requestPaymentTypes,
        purposeOperational,
        purposeOther,
        purposeInvestReturns,
        investBucketByType,
      })
      const data = await patchTenantCashflowReportSettings({ cashflow_source: cashflowSource, cashflow_config })
      applyServerRow(data)
      if (cashflowSource === 'backend') {
        const d = await getTenantCashflowReportSettings({ cashflowDiagnostics: true })
        applyServerRow(d)
      }
      await refetchPurposePool(requestPaymentTypes)
      message.success('Настройки Cashflow сохранены')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Не удалось сохранить')
    } finally {
      setSaving(false)
    }
  }

  const backendHint = useMemo(
    () =>
      cashflowSource === 'backend'
        ? 'Backend Cashflow: те же параметры, что у PnL, но расходы заявок берутся по дате фактической оплаты (expense_year/month/day), без амортизации; выплаты по инвестициям — по дате выплаты (date), не по месяцу начисления.'
        : null,
    [cashflowSource],
  )

  if (gateLoading) {
    return <Card loading style={{ maxWidth: 960 }} />
  }
  if (!allowed) {
    return (
      <Alert
        type="warning"
        showIcon
        message="Доступ ограничен"
        description={
          gateError ??
          'Изменение настроек Cashflow доступно только администратору компании (роль admin).'
        }
      />
    )
  }

  return (
    <div style={{ maxWidth: 960 }}>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Отчёт Cashflow — источник данных
      </Typography.Title>
      <Typography.Paragraph type="secondary">
        Выбор между workflow в n8n и расчётом на сервере. Параметры блока «Расчёт в приложении» обязательны при
        сохранении с этим источником.
      </Typography.Paragraph>

      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} /> : null}
      {backendHint ? <Alert type="info" showIcon message={backendHint} style={{ marginBottom: 16 }} /> : null}

      {purposePoolLoadError ? (
        <Alert
          type="warning"
          showIcon
          message="Список назначений платежа"
          description={purposePoolLoadError}
          style={{ marginBottom: 16 }}
        />
      ) : null}
      {cashflowSource === 'backend' && diagnosticsError ? (
        <Alert type="warning" showIcon message="Диагностика" description={diagnosticsError} style={{ marginBottom: 16 }} />
      ) : null}
      {unassignedFromPaidRequests.length > 0 ? (
        <Alert
          type="error"
          showIcon
          message="Назначения не попали ни в одну корзину (оплаченные заявки в области backend Cashflow)"
          description={
            <div>
              <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
                Перенесите значения в одну из трёх корзин ниже — подсветка обновится сразу, без сохранения.
              </Typography.Paragraph>
              <Space wrap size={[6, 6]}>
                {unassignedFromPaidRequests.map((row) => (
                  <Tag key={row.purpose} color="volcano">
                    {row.purpose} ({row.count})
                  </Tag>
                ))}
              </Space>
            </div>
          }
          style={{ marginBottom: 16 }}
        />
      ) : null}
      {unassignedFromPoolOnly.length > 0 ? (
        <Alert
          type="info"
          showIcon
          message="Назначения из справочника вне корзин"
          description={
            <Space wrap size={[6, 6]}>
              {unassignedFromPoolOnly.map((p) => (
                <Tag key={p}>{p}</Tag>
              ))}
            </Space>
          }
          style={{ marginBottom: 16 }}
        />
      ) : null}

      <Card loading={loading}>
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <div>
            <Typography.Text strong>Источник Cashflow</Typography.Text>
            <Select<'n8n' | 'backend'>
              style={{ width: '100%', marginTop: 8 }}
              value={cashflowSource}
              onChange={setCashflowSource}
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
            <Typography.Text strong>Типы оплаты заявок в расходах Cashflow</Typography.Text>
            <Typography.Paragraph type="secondary" style={{ marginBottom: 8, marginTop: 4 }}>
              Ничего не выбрано — пустой whitelist: заявки в расходы Cashflow не попадают.
            </Typography.Paragraph>
            <Select
              mode="multiple"
              allowClear
              style={{ width: '100%' }}
              placeholder="Выберите типы оплаты"
              value={requestPaymentTypes}
              onChange={(v) => {
                setRequestPaymentTypes(v)
                void refetchPurposePool(v)
              }}
              options={[...REQUEST_PAYMENT_OPTIONS]}
            />
          </div>

          <div>
            <Typography.Text strong>Исключить операции кассы (подписи операций)</Typography.Text>
            <Input.TextArea
              style={{ marginTop: 8 }}
              rows={3}
              placeholder="По одному значению на строку"
              value={cashExclude}
              onChange={(e) => setCashExclude(e.target.value)}
            />
          </div>

          <div>
            <Typography.Text strong>Исключить категории заявок</Typography.Text>
            <Input.TextArea
              style={{ marginTop: 8 }}
              rows={3}
              placeholder="По одному значению на строку"
              value={requestExclude}
              onChange={(e) => setRequestExclude(e.target.value)}
            />
          </div>

          <Typography.Title level={5}>Назначения платежа заявок (три корзины, без пересечений)</Typography.Title>
          <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
            Пул ограничен выбранными выше «Типами оплаты заявок в расходах Cashflow»; активные назначения из формы заявки и
            значения из заявок по этим типам. При backend Cashflow сюда же подмешиваются назначения из диагностики. Выбор в
            одной корзине убирает то же значение из двух других.
          </Typography.Paragraph>
          <Space align="start" wrap style={{ width: '100%' }}>
            <div style={{ flex: 1, minWidth: 220 }}>
              <Typography.Text strong>Операционные расходы</Typography.Text>
              <Select
                mode="multiple"
                allowClear
                showSearch
                optionFilterProp="label"
                style={{ width: '100%', marginTop: 8 }}
                placeholder="Выберите назначения"
                options={purposeSelectOptions}
                value={purposeOperational}
                onChange={(v) => {
                  setPurposeOperational(v)
                  setPurposeOther((prev) => prev.filter((p) => !v.includes(p)))
                  setPurposeInvestReturns((prev) => prev.filter((p) => !v.includes(p)))
                }}
              />
            </div>
            <div style={{ flex: 1, minWidth: 220 }}>
              <Typography.Text strong>Прочие расходы</Typography.Text>
              <Select
                mode="multiple"
                allowClear
                showSearch
                optionFilterProp="label"
                style={{ width: '100%', marginTop: 8 }}
                placeholder="Выберите назначения"
                options={purposeSelectOptions}
                value={purposeOther}
                onChange={(v) => {
                  setPurposeOther(v)
                  setPurposeOperational((prev) => prev.filter((p) => !v.includes(p)))
                  setPurposeInvestReturns((prev) => prev.filter((p) => !v.includes(p)))
                }}
              />
            </div>
            <div style={{ flex: 1, minWidth: 220 }}>
              <Typography.Text strong>Третья корзина (ключ API invest_returns)</Typography.Text>
              <Select
                mode="multiple"
                allowClear
                showSearch
                optionFilterProp="label"
                style={{ width: '100%', marginTop: 8 }}
                placeholder="Выберите назначения"
                options={purposeSelectOptions}
                value={purposeInvestReturns}
                onChange={(v) => {
                  setPurposeInvestReturns(v)
                  setPurposeOperational((prev) => prev.filter((p) => !v.includes(p)))
                  setPurposeOther((prev) => prev.filter((p) => !v.includes(p)))
                }}
              />
            </div>
          </Space>

          <Typography.Title level={5}>Типы выплат по инвестициям (ровно одна корзина на тип)</Typography.Title>
          <Space direction="vertical" style={{ width: '100%' }}>
            {INVEST_RETURN_TYPES.map((t) => (
              <div key={t.value} style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                <Typography.Text style={{ minWidth: 160 }}>{t.label}</Typography.Text>
                <Select<InvestBucket>
                  style={{ minWidth: 220 }}
                  value={investBucketByType[t.value] ?? 'operational'}
                  onChange={(v) => setInvestBucketByType((prev) => ({ ...prev, [t.value]: v }))}
                  options={[
                    { value: 'operational', label: 'Операционные расходы' },
                    { value: 'other', label: 'Прочие расходы' },
                    { value: 'invest_returns', label: 'Третья корзина (invest_returns)' },
                  ]}
                />
              </div>
            ))}
          </Space>

          <Space wrap>
            <Button type="primary" onClick={() => void onSave()} loading={saving}>
              Сохранить
            </Button>
            {cashflowSource === 'backend' ? (
              <Button onClick={() => void loadDiagnostics()}>Обновить диагностику назначений</Button>
            ) : null}
          </Space>

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
