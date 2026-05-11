import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Input, Select, Space, Typography, message } from 'antd'
import {
  getSettingsAccess,
  getTenantReportSettings,
  patchTenantReportSettings,
  type PnlReportSettingsSnapshot,
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

function buildConfigFromForm(fields: {
  startMonth: string
  incomeTaxPurpose: string
  cashExclude: string
  requestExclude: string
  investExclude: string
}): PnlReportSettingsSnapshot {
  return {
    start_month: fields.startMonth.trim(),
    income_tax_payment_purpose: fields.incomeTaxPurpose.trim(),
    cash_exclude_operations: splitList(fields.cashExclude),
    request_exclude_categories: splitList(fields.requestExclude),
    invest_return_exclude_types: splitList(fields.investExclude),
  }
}

export function PnlReportSettingsPage() {
  const [gateLoading, setGateLoading] = useState(true)
  const [allowed, setAllowed] = useState(false)
  const [gateError, setGateError] = useState<string | null>(null)

  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [pnlSource, setPnlSource] = useState<'n8n' | 'backend'>('n8n')
  const [startMonth, setStartMonth] = useState('')
  const [incomeTaxPurpose, setIncomeTaxPurpose] = useState('')
  const [cashExclude, setCashExclude] = useState('')
  const [requestExclude, setRequestExclude] = useState('')
  const [investExclude, setInvestExclude] = useState('')
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
    setRequestExclude(joinList(c.request_exclude_categories))
    setInvestExclude(joinList(c.invest_return_exclude_types))
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

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getTenantReportSettings()
      applyServerRow(data)
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
      const pnl_config = buildConfigFromForm({
        startMonth,
        incomeTaxPurpose,
        cashExclude,
        requestExclude,
        investExclude,
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
            <Input
              style={{ marginTop: 8 }}
              placeholder="Текст для сопоставления в выписках"
              value={incomeTaxPurpose}
              onChange={(e) => setIncomeTaxPurpose(e.target.value)}
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

          <div>
            <Typography.Text strong>Исключить типы возвратов по инвестициям</Typography.Text>
            <Input.TextArea
              style={{ marginTop: 8 }}
              rows={3}
              placeholder="По одному значению на строку"
              value={investExclude}
              onChange={(e) => setInvestExclude(e.target.value)}
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
