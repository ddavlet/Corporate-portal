import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Divider, Select, Skeleton, Space, Switch, Typography, message } from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'
import { Link, useNavigate } from 'react-router-dom'

import {
  getBankAccounts,
  getCashRegisters,
  getInvestmentFundingConfig,
  saveInvestmentFundingConfig,
  type BankAccountDto,
  type CashRegisterDto,
  type InvestmentFundingConfigDto,
} from '../../lib/api'

export function InvestmentFundingConfigPage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [config, setConfig] = useState<InvestmentFundingConfigDto | null>(null)
  const [cashRegisters, setCashRegisters] = useState<CashRegisterDto[]>([])
  const [bankAccounts, setBankAccounts] = useState<BankAccountDto[]>([])
  const [isEnabled, setIsEnabled] = useState(false)
  const [cashWalletId, setCashWalletId] = useState<number | null>(null)
  const [bankWalletId, setBankWalletId] = useState<number | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setError(null)
      try {
        const [cfg, registers, accounts] = await Promise.all([
          getInvestmentFundingConfig(),
          getCashRegisters(),
          // Модуль банка может быть выключен — счёт тогда просто недоступен для выбора.
          getBankAccounts().catch(() => [] as BankAccountDto[]),
        ])
        if (cancelled) return
        setConfig(cfg)
        setIsEnabled(cfg.is_enabled)
        setCashWalletId(cfg.cash_wallet_id)
        setBankWalletId(cfg.bank_wallet_id)
        setCashRegisters(registers)
        setBankAccounts(accounts)
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Ошибка загрузки')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  // Опции — Wallet id (а не id кассы/счёта): именно его ждёт бэкенд.
  const cashOptions = useMemo(
    () =>
      cashRegisters
        .filter((r) => r.is_active || r.wallet_id === cashWalletId)
        .map((r) => ({ value: r.wallet_id, label: `${r.name} (${r.currency})` })),
    [cashRegisters, cashWalletId],
  )
  const bankOptions = useMemo(
    () => bankAccounts.map((a) => ({ value: a.wallet_id, label: a.account_no ? `${a.label} (${a.account_no})` : a.label })),
    [bankAccounts],
  )

  const chainMissing = config != null && !config.has_project_approval_chain

  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      const next = await saveInvestmentFundingConfig({
        is_enabled: isEnabled,
        cash_wallet_id: cashWalletId,
        bank_wallet_id: bankWalletId,
      })
      setConfig(next)
      setIsEnabled(next.is_enabled)
      setCashWalletId(next.cash_wallet_id)
      setBankWalletId(next.bank_wallet_id)
      message.success('Сохранено')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Ошибка сохранения')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card>
      <Button type="link" icon={<ArrowLeftOutlined />} onClick={() => navigate('/settings')} style={{ padding: 0 }}>
        Назад к настройкам
      </Button>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Инвестиционный режим
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        Вложения инвестора оформляются сбором заявок на расход; при подтверждении вложения сумма приходует в
        инвестиционную кассу.
      </Typography.Paragraph>

      <Divider />
      {loading ? <Skeleton active /> : null}
      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} /> : null}

      {!loading && config ? (
        <Space direction="vertical" size={16} style={{ display: 'flex' }}>
          {chainMissing ? (
            <Alert
              type="warning"
              showIcon
              message="Сначала настройте согласование заявок на вложение"
              description={<Link to="/settings/investment-project-approval-config">Перейти к настройке согласования</Link>}
            />
          ) : null}

          <Space>
            <Switch
              aria-label="Включить инвестиционный режим"
              checked={isEnabled}
              // Без цепочки согласования режим нельзя включить, но выключить — всегда можно
              // (как на backend: цепочка проверяется только при переходе выкл→вкл сохранённого режима).
              disabled={chainMissing && !config.is_enabled}
              onChange={setIsEnabled}
            />
            <Typography.Text>Включить инвестиционный режим</Typography.Text>
          </Space>

          <div>
            <Typography.Text strong style={{ display: 'block', marginBottom: 4 }}>
              Инвестиционная касса
            </Typography.Text>
            <Select
              aria-label="Инвестиционная касса"
              style={{ width: 360, maxWidth: '100%' }}
              allowClear
              placeholder="Выберите кассу"
              value={cashWalletId ?? undefined}
              onChange={(v) => setCashWalletId(v ?? null)}
              options={cashOptions}
            />
          </div>

          <div>
            <Typography.Text strong style={{ display: 'block', marginBottom: 4 }}>
              Счёт
            </Typography.Text>
            <Select
              aria-label="Счёт"
              style={{ width: 360, maxWidth: '100%' }}
              allowClear
              placeholder="Выберите счёт"
              value={bankWalletId ?? undefined}
              onChange={(v) => setBankWalletId(v ?? null)}
              options={bankOptions}
            />
          </div>

          <Button type="primary" loading={saving} onClick={() => void save()}>
            Сохранить
          </Button>
        </Space>
      ) : null}
    </Card>
  )
}
