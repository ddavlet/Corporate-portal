import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Input, Select, Typography, message } from 'antd'
import { Link } from 'react-router-dom'
import {
  getSettingsAccess,
  getTenantCashflowReportSettings,
  patchTenantCashflowReportSettings,
  type PnlReportSettingsSnapshot,
} from '../../lib/api'

export function CashflowReportSettingsPage() {
  const [gateLoading, setGateLoading] = useState(true)
  const [allowed, setAllowed] = useState(false)
  const [gateError, setGateError] = useState<string | null>(null)

  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [cashflowSource, setCashflowSource] = useState<'n8n' | 'backend'>('n8n')
  const [cashflowOpeningBalance, setCashflowOpeningBalance] = useState('')
  const [pnlConfig, setPnlConfig] = useState<PnlReportSettingsSnapshot>({})
  const [pnlConfigError, setPnlConfigError] = useState<string | null>(null)
  const [updatedAt, setUpdatedAt] = useState<string | null>(null)

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
    setPnlConfigError(null)
    try {
      const data = await getTenantCashflowReportSettings()
      setCashflowSource(data.cashflow_source)
      setCashflowOpeningBalance(String(data.cashflow_config?.opening_balance ?? '').trim())
      setPnlConfig(data.pnl_config ?? {})
      setUpdatedAt(typeof data.updated_at === 'string' ? data.updated_at : null)
      if (data.cashflow_diagnostics?.error) {
        setPnlConfigError(data.cashflow_diagnostics.error)
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Не удалось загрузить настройки')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!allowed) return
    void load()
  }, [allowed, load])

  const onSave = async () => {
    setSaving(true)
    setError(null)
    try {
      const data = await patchTenantCashflowReportSettings({
        cashflow_source: cashflowSource,
        cashflow_config: { opening_balance: cashflowOpeningBalance.trim() || '0' },
      })
      setCashflowSource(data.cashflow_source)
      setCashflowOpeningBalance(String(data.cashflow_config?.opening_balance ?? '').trim())
      setPnlConfig(data.pnl_config ?? {})
      setUpdatedAt(typeof data.updated_at === 'string' ? data.updated_at : null)
      message.success('Настройки Cashflow сохранены')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Не удалось сохранить')
    } finally {
      setSaving(false)
    }
  }

  const pnlReady =
    Boolean(pnlConfig.start_month?.trim()) &&
    (pnlConfig.request_payment_types_for_pnl?.length ?? 0) > 0

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
          'Изменение настроек Cashflow доступно только администратору компании (роль admin).'
        }
      />
    )
  }

  return (
    <div style={{ maxWidth: 720 }}>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Отчёт Cashflow — источник данных
      </Typography.Title>
      <Typography.Paragraph type="secondary">
        Фильтры (типы оплаты, назначения платежа, корзины расходов, стартовый месяц) общие с отчётом PnL — их можно задать на{' '}
        <Link to="/settings/pnl-report-config">странице PnL</Link>.{' '}
        <strong>Начальный остаток для Cashflow</strong> задаётся ниже отдельно от начального остатка PnL. Для backend
        Cashflow расходы заявок считаются по дате фактической оплаты (без амортизации); выплаты по инвестициям — по дате
        выплаты.
      </Typography.Paragraph>

      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} /> : null}
      {cashflowSource === 'backend' && !pnlReady ? (
        <Alert
          type="warning"
          showIcon
          message="Сначала настройте backend PnL"
          description={
            <>
              Включите расчёт PnL в приложении и заполните параметры на{' '}
              <Link to="/settings/pnl-report-config">странице PnL</Link> — те же правила будут
              использоваться для Cashflow.
            </>
          }
          style={{ marginBottom: 16 }}
        />
      ) : null}
      {pnlConfigError ? (
        <Alert type="warning" showIcon message="Конфиг PnL" description={pnlConfigError} style={{ marginBottom: 16 }} />
      ) : null}

      <Card loading={loading}>
        <div style={{ marginBottom: 16 }}>
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

        <div style={{ marginBottom: 16 }}>
          <Typography.Text strong>Начальный остаток (Cashflow)</Typography.Text>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 8, marginTop: 4 }}>
            Остаток на начало месяца «Стартовый месяц» из настроек PnL — только для суммарного остатка в отчёте Cashflow.
            Не связан с полем начального остатка на странице PnL.
          </Typography.Paragraph>
          <Input
            placeholder="Например 1250000 или 0"
            value={cashflowOpeningBalance}
            onChange={(e) => setCashflowOpeningBalance(e.target.value)}
          />
        </div>

        {pnlConfig.start_month ? (
          <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
            Стартовый месяц из PnL: <Typography.Text code>{pnlConfig.start_month}</Typography.Text>
            {pnlConfig.request_payment_types_for_pnl?.length
              ? ` · типов оплаты в расходах: ${pnlConfig.request_payment_types_for_pnl.length}`
              : ''}
          </Typography.Paragraph>
        ) : null}

        <Button type="primary" onClick={() => void onSave()} loading={saving}>
          Сохранить
        </Button>

        {updatedAt ? (
          <Typography.Text type="secondary" style={{ display: 'block', marginTop: 12, fontSize: 12 }}>
            Обновлено: {updatedAt}
          </Typography.Text>
        ) : null}
      </Card>
    </div>
  )
}
