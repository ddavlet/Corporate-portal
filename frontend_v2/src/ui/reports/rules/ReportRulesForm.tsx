import { Alert, Button, Input, Select, Skeleton, Space, Tag, Typography } from 'antd'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { getTenantPnlPaymentPurposePool } from '../../../lib/api'
import { notifyApiSuccess } from '../../../lib/apiNotify'
import {
  getReportRules,
  updateReportRules,
  type ReportKind,
  type ReportRulesResponse,
  type ReportSource,
  type UnassignedPurpose,
} from '../../../lib/reportsApi'
import { requestPaymentTypeSelectOptions } from '../../../lib/requestPaymentTypes'
import { REPORT_RULES_FORMS } from './reportRulesForms'
import {
  INVEST_BUCKET_OPTIONS,
  INVEST_RETURN_TYPES,
  buildRulesFromForm,
  formFromRules,
  movePurposes,
  uniqTrimmedStrings,
  type InvestBucket,
  type PurposeBucket,
  type ReportRulesFormValues,
} from './reportRulesModel'

type Props = {
  report: ReportKind
  /** After a successful save, e.g. to reload the open report. */
  onSaved?: () => void
}

type Diagnostics = { items: UnassignedPurpose[] | null; error: string | null }

const NO_DIAGNOSTICS: Diagnostics = { items: null, error: null }

const SOURCE_OPTIONS: { value: ReportSource; label: string }[] = [
  { value: 'n8n', label: 'n8n (как настроено в автоматизации)' },
  { value: 'backend', label: 'Расчёт в приложении (backend)' },
]

const BACKEND_HINT =
  'Расчёт в приложении: задайте стартовый месяц, начальный остаток на его начало (необязательно), типы оплаты заявок (пустой список — ни одна заявка в расходах), три непересекающихся набора назначений платежа и распределение всех четырёх типов выплат по инвестициям.'

const BUCKET_LABELS: Record<PurposeBucket, string> = {
  purposeOperational: 'Операционные расходы',
  purposeOther: 'Прочие расходы',
  purposeInvestReturns: 'Третья корзина (ключ API invest_returns)',
}

function diagnosticsOf(data: ReportRulesResponse): Diagnostics {
  const error = data.diagnostics?.error ?? null
  return { items: error ? null : (data.diagnostics?.unassigned_payment_purposes ?? null), error }
}

function messageOf(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

/** One report's data source and calculation rules; the drawer on «Отчёты» and the settings pages show this form. */
export function ReportRulesForm({ report, onSaved }: Props) {
  const spec = REPORT_RULES_FORMS[report]
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [source, setSource] = useState<ReportSource>('n8n')
  const [values, setValues] = useState<ReportRulesFormValues>(() => formFromRules({}))
  const [updatedAt, setUpdatedAt] = useState<string | null>(null)
  const [diagnostics, setDiagnostics] = useState<Diagnostics>(NO_DIAGNOSTICS)
  const [purposePool, setPurposePool] = useState<string[]>([])
  const [purposePoolError, setPurposePoolError] = useState<string | null>(null)

  const update = (patch: Partial<ReportRulesFormValues>) => setValues((previous) => ({ ...previous, ...patch }))

  const refetchPurposePool = useCallback(async (types: string[]) => {
    setPurposePoolError(null)
    try {
      setPurposePool((await getTenantPnlPaymentPurposePool({ forPnlPaymentTypes: types })).purposes)
    } catch (e: unknown) {
      setPurposePoolError(messageOf(e, 'Не удалось обновить список назначений'))
    }
  }, [])

  /** Diagnostics check the rules against paid requests; only a report calculated in the app uses its rules. */
  const loadDiagnostics = useCallback(
    async (reportSource: ReportSource) => {
      if (reportSource !== 'backend') {
        setDiagnostics(NO_DIAGNOSTICS)
        return
      }
      try {
        setDiagnostics(diagnosticsOf(await getReportRules(report, { diagnostics: true })))
      } catch {
        setDiagnostics(NO_DIAGNOSTICS)
      }
    },
    [report],
  )

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const data = await getReportRules(report)
      setSource(data.source)
      setValues(formFromRules(data.rules))
      setUpdatedAt(data.updated_at)
      await loadDiagnostics(data.source)
      await refetchPurposePool(data.rules.request_payment_types_for_pnl ?? [])
    } catch (e: unknown) {
      setLoadError(messageOf(e, 'Не удалось загрузить правила'))
    } finally {
      setLoading(false)
    }
  }, [report, loadDiagnostics, refetchPurposePool])

  useEffect(() => {
    void load()
  }, [load])

  const save = async () => {
    setSaving(true)
    setSaveError(null)
    let saved: ReportRulesResponse
    try {
      saved = await updateReportRules(report, { source, rules: buildRulesFromForm(values, spec) })
    } catch (e: unknown) {
      setSaveError(messageOf(e, 'Не удалось сохранить'))
      setSaving(false)
      return
    }
    setSource(saved.source)
    setValues(formFromRules(saved.rules))
    setUpdatedAt(saved.updated_at)
    setSaving(false)
    notifyApiSuccess('Правила сохранены')
    onSaved?.()
    await loadDiagnostics(saved.source)
    await refetchPurposePool(saved.rules.request_payment_types_for_pnl ?? [])
  }

  const diagnosticPurposes = useMemo(
    () => uniqTrimmedStrings((diagnostics.items ?? []).map((item) => item.purpose)),
    [diagnostics.items],
  )

  const purposeOptions = useMemo(
    () =>
      uniqTrimmedStrings([
        ...purposePool,
        ...diagnosticPurposes,
        ...values.purposeOperational,
        ...values.purposeOther,
        ...values.purposeInvestReturns,
      ])
        .sort((a, b) => a.localeCompare(b, 'ru'))
        .map((value) => ({ value, label: value })),
    [purposePool, diagnosticPurposes, values.purposeOperational, values.purposeOther, values.purposeInvestReturns],
  )

  if (loading) return <Skeleton active />
  if (loadError) {
    return (
      <Alert
        type="error"
        showIcon
        message={loadError}
        action={
          <Button size="small" onClick={() => void load()}>
            Повторить
          </Button>
        }
      />
    )
  }

  const assigned = new Set([...values.purposeOperational, ...values.purposeOther, ...values.purposeInvestReturns])
  const unassignedPaid = (diagnostics.items ?? []).filter((item) => !assigned.has(item.purpose))
  const unassignedPoolOnly = purposeOptions
    .map((option) => option.value)
    .filter((purpose) => !assigned.has(purpose) && !diagnosticPurposes.includes(purpose))

  const bucketSelect = (bucket: PurposeBucket) => (
    <div key={bucket} style={{ flex: 1, minWidth: 220 }}>
      <Typography.Text strong>{BUCKET_LABELS[bucket]}</Typography.Text>
      <Select
        mode="multiple"
        allowClear
        showSearch
        optionFilterProp="label"
        aria-label={BUCKET_LABELS[bucket]}
        style={{ width: '100%', marginTop: 8 }}
        placeholder="Выберите назначения"
        options={purposeOptions}
        value={values[bucket]}
        onChange={(picked: string[]) => setValues((previous) => movePurposes(previous, bucket, picked))}
      />
    </div>
  )

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      {saveError ? <Alert type="error" showIcon message={saveError} /> : null}
      {source === 'backend' ? <Alert type="info" showIcon message={BACKEND_HINT} /> : null}
      {purposePoolError ? (
        <Alert type="warning" showIcon message="Список назначений платежа" description={purposePoolError} />
      ) : null}
      {source === 'backend' && diagnostics.error ? (
        <Alert type="warning" showIcon message="Диагностика" description={diagnostics.error} />
      ) : null}
      {unassignedPaid.length > 0 ? (
        <Alert
          type="error"
          showIcon
          message="Назначения не попали ни в одну корзину (оплаченные заявки в области отчёта)"
          description={
            <div>
              <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
                Перенесите значения в одну из трёх корзин ниже — подсветка обновится сразу, без сохранения.
              </Typography.Paragraph>
              <Space wrap size={[6, 6]}>
                {unassignedPaid.map((item) => (
                  <Tag key={item.purpose} color="volcano">
                    {`${item.purpose} (${item.count})`}
                  </Tag>
                ))}
              </Space>
            </div>
          }
        />
      ) : null}
      {unassignedPoolOnly.length > 0 ? (
        <Alert
          type="info"
          showIcon
          message="Назначения из справочника вне корзин"
          description={
            <Space wrap size={[6, 6]}>
              {unassignedPoolOnly.map((purpose) => (
                <Tag key={purpose}>{purpose}</Tag>
              ))}
            </Space>
          }
        />
      ) : null}

      <div>
        <Typography.Text strong>Источник данных</Typography.Text>
        <Select<ReportSource>
          aria-label="Источник данных"
          style={{ width: '100%', marginTop: 8 }}
          value={source}
          onChange={setSource}
          options={SOURCE_OPTIONS}
        />
        <Typography.Paragraph type="secondary" style={{ margin: '4px 0 0' }}>
          {spec.expenseDates}
        </Typography.Paragraph>
      </div>

      <div>
        <Typography.Text strong>Стартовый месяц периода</Typography.Text>
        <Input
          aria-label="Стартовый месяц периода"
          style={{ marginTop: 8 }}
          placeholder="YYYY-MM, например 2026-01"
          value={values.startMonth}
          onChange={(e) => update({ startMonth: e.target.value })}
        />
      </div>

      <div>
        <Typography.Text strong>Начальный остаток</Typography.Text>
        <Typography.Paragraph type="secondary" style={{ margin: '4px 0 8px' }}>
          Остаток на начало стартового месяца (до его операций), для накопительных строк отчёта. Оставьте пустым или 0,
          если не нужен.
        </Typography.Paragraph>
        <Input
          aria-label="Начальный остаток"
          placeholder="Например 1250000 или 0"
          value={values.openingBalance}
          onChange={(e) => update({ openingBalance: e.target.value })}
        />
      </div>

      <div>
        <Typography.Text strong>Типы оплаты заявок в расходах</Typography.Text>
        <Typography.Paragraph type="secondary" style={{ margin: '4px 0 8px' }}>
          Ничего не выбрано — заявки в расходы не попадают.
        </Typography.Paragraph>
        <Select
          mode="multiple"
          allowClear
          aria-label="Типы оплаты заявок в расходах"
          style={{ width: '100%' }}
          placeholder="Выберите типы оплаты"
          value={values.requestPaymentTypes}
          onChange={(types: string[]) => {
            update({ requestPaymentTypes: types })
            void refetchPurposePool(types)
          }}
          options={requestPaymentTypeSelectOptions()}
        />
      </div>

      <div>
        <Typography.Text strong>Исключить операции кассы (подписи операций)</Typography.Text>
        <Input.TextArea
          aria-label="Исключить операции кассы"
          style={{ marginTop: 8 }}
          rows={3}
          placeholder="По одному значению на строку"
          value={values.cashExclude}
          onChange={(e) => update({ cashExclude: e.target.value })}
        />
      </div>

      {spec.bankExclusions ? (
        <div>
          <Typography.Text strong>Исключить банковские поступления (фразы в назначении платежа)</Typography.Text>
          <Typography.Paragraph type="secondary" style={{ margin: '4px 0 8px' }}>
            Поступление в банк не попадёт в выручку, если его назначение платежа содержит любую из фраз (без учёта
            регистра). Например: «пополнение уставного».
          </Typography.Paragraph>
          <Input.TextArea
            aria-label="Исключить банковские поступления"
            rows={3}
            placeholder="По одной фразе на строку, например: пополнение уставного"
            value={values.bankExclude}
            onChange={(e) => update({ bankExclude: e.target.value })}
          />
        </div>
      ) : null}

      <div>
        <Typography.Text strong>Исключить категории заявок</Typography.Text>
        <Input.TextArea
          aria-label="Исключить категории заявок"
          style={{ marginTop: 8 }}
          rows={3}
          placeholder="По одному значению на строку"
          value={values.requestExclude}
          onChange={(e) => update({ requestExclude: e.target.value })}
        />
      </div>

      <Typography.Title level={5} style={{ margin: 0 }}>
        Назначения платежа заявок (три корзины, без пересечений)
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
        В списке — назначения выбранных выше типов оплаты: активные из формы заявки и уже встречавшиеся в заявках, при
        расчёте в приложении — ещё и из диагностики. Выбор в одной корзине убирает то же значение из двух других.
      </Typography.Paragraph>
      <Space align="start" wrap style={{ width: '100%' }}>
        {bucketSelect('purposeOperational')}
        {bucketSelect('purposeOther')}
        {bucketSelect('purposeInvestReturns')}
      </Space>

      <Typography.Title level={5} style={{ margin: 0 }}>
        Типы выплат по инвестициям (ровно одна корзина на тип)
      </Typography.Title>
      <Space direction="vertical" style={{ width: '100%' }}>
        {INVEST_RETURN_TYPES.map((type) => (
          <div key={type.value} style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <Typography.Text style={{ minWidth: 160 }}>{type.label}</Typography.Text>
            <Select<InvestBucket>
              aria-label={type.label}
              style={{ minWidth: 220 }}
              value={values.investBucketByType[type.value] ?? 'operational'}
              onChange={(bucket) => update({ investBucketByType: { ...values.investBucketByType, [type.value]: bucket } })}
              options={INVEST_BUCKET_OPTIONS}
            />
          </div>
        ))}
      </Space>

      <Space wrap>
        <Button type="primary" loading={saving} onClick={() => void save()}>
          Сохранить
        </Button>
        {source === 'backend' ? (
          <Button onClick={() => void loadDiagnostics(source)}>Обновить диагностику назначений</Button>
        ) : null}
      </Space>

      {updatedAt ? (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {`Обновлено: ${updatedAt}`}
        </Typography.Text>
      ) : null}
    </Space>
  )
}
