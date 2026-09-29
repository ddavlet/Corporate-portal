import { useEffect, useState } from 'react'
import { Alert, Button, Card, Divider, InputNumber, Result, Select, Skeleton, Space, Switch, Table, Tag, Typography, message } from 'antd'
import { ArrowLeftOutlined, DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'

import {
  CashWithdrawalConfigUnavailableError,
  getCashWithdrawalConfig,
  saveCashWithdrawalConfig,
  type CashWithdrawalConfigDto,
  type CashWithdrawalConfigOptions,
  type CashWithdrawalConfigResponse,
  type CashWithdrawalRuleDto,
} from '../../lib/cashWithdrawalsApi'

function splitResponse(res: CashWithdrawalConfigResponse): [CashWithdrawalConfigDto, CashWithdrawalConfigOptions] {
  const { options, ...config } = res
  return [config, options]
}

function UserPicker({
  value,
  onChange,
  options,
}: {
  value: number[]
  onChange: (v: number[]) => void
  options: CashWithdrawalConfigOptions['users']
}) {
  const byId = new Map(options.map((u) => [u.id, u]))
  return (
    <Space direction="vertical" style={{ display: 'flex' }}>
      <Select
        mode="multiple"
        style={{ width: '100%', maxWidth: 520 }}
        placeholder="Выберите пользователей"
        value={value}
        onChange={onChange}
        options={options.map((u) => ({ value: u.id, label: u.label }))}
        optionFilterProp="label"
      />
      <Space wrap>
        {value
          .map((id) => byId.get(id))
          .filter((u): u is NonNullable<typeof u> => Boolean(u) && !u!.has_telegram)
          .map((u) => (
            <Tag key={u.id} color="warning">
              {u.label}: нет Telegram
            </Tag>
          ))}
      </Space>
    </Space>
  )
}

export function CashWithdrawalConfigPage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [unavailable, setUnavailable] = useState(false)
  const [data, setData] = useState<CashWithdrawalConfigDto | null>(null)
  const [options, setOptions] = useState<CashWithdrawalConfigOptions | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const [cfg, opts] = splitResponse(await getCashWithdrawalConfig())
        if (cancelled) return
        setData(cfg)
        setOptions(opts)
      } catch (e: unknown) {
        if (cancelled) return
        if (e instanceof CashWithdrawalConfigUnavailableError) setUnavailable(true)
        else setError(e instanceof Error ? e.message : 'Ошибка загрузки')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const patch = (next: Partial<CashWithdrawalConfigDto>) => setData((prev) => (prev ? { ...prev, ...next } : prev))
  const setRule = (index: number, next: Partial<CashWithdrawalRuleDto>) =>
    setData((prev) => (prev ? { ...prev, rules: prev.rules.map((r, i) => (i === index ? { ...r, ...next } : r)) } : prev))

  const save = async () => {
    if (!data) return
    if (data.rules.some((r) => !r.payment_type || !r.payment_purpose || !r.wallet_id)) {
      message.warning('Заполните тип оплаты, назначение и кассу в каждом правиле')
      return
    }
    setSaving(true)
    setError(null)
    try {
      const [cfg, opts] = splitResponse(await saveCashWithdrawalConfig(data))
      setData(cfg)
      setOptions(opts)
      message.success('Сохранено')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Ошибка сохранения')
    } finally {
      setSaving(false)
    }
  }

  const back = (
    <Button type="link" icon={<ArrowLeftOutlined />} onClick={() => navigate('/settings')} style={{ padding: 0 }}>
      Назад к настройкам
    </Button>
  )

  if (unavailable) {
    return (
      <Card>
        {back}
        <Result status="warning" title="Настройка недоступна" subTitle="Её меняет администратор или директор компании." />
      </Card>
    )
  }

  const purposesFor = (paymentType: string) =>
    options?.payment_purposes.find((p) => p.payment_type === paymentType)?.purposes ?? []

  return (
    <Card>
      {back}
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Снятие наличных — подтверждение поступления
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        Когда заявка по правилу ниже оплачена, в Telegram приходит карточка «Ожидается поступление в кассу». Кнопка
        «✅ Деньги получены» создаёт доход в кассе. Если никто не подтвердил, приходят предупреждения.
      </Typography.Paragraph>
      <Divider />
      {loading ? <Skeleton active /> : null}
      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} /> : null}

      {!loading && data && options ? (
        <Space direction="vertical" size={20} style={{ display: 'flex' }}>
          <Space align="center">
            <Switch checked={data.is_active} onChange={(v) => patch({ is_active: v })} />
            <Typography.Text>Включено</Typography.Text>
          </Space>

          <div>
            <Typography.Title level={5}>Правила</Typography.Title>
            <Table<CashWithdrawalRuleDto & { key: number }>
              size="small"
              pagination={false}
              dataSource={data.rules.map((r, i) => ({ ...r, key: i }))}
              columns={[
                {
                  title: 'Тип оплаты',
                  render: (_, r) => (
                    <Select
                      style={{ width: 180 }}
                      value={r.payment_type || undefined}
                      placeholder="Тип оплаты"
                      onChange={(v: string) => setRule(r.key, { payment_type: v, payment_purpose: '' })}
                      options={options.payment_purposes.map((p) => ({ value: p.payment_type, label: p.payment_type }))}
                    />
                  ),
                },
                {
                  title: 'Назначение',
                  render: (_, r) => (
                    <Select
                      style={{ width: 280 }}
                      value={r.payment_purpose || undefined}
                      placeholder="Назначение платежа"
                      onChange={(v: string) => setRule(r.key, { payment_purpose: v })}
                      options={purposesFor(r.payment_type).map((p) => ({ value: p, label: p }))}
                      showSearch
                    />
                  ),
                },
                {
                  title: 'Касса',
                  render: (_, r) => (
                    <Select
                      style={{ width: 220 }}
                      value={r.wallet_id ?? undefined}
                      placeholder="Касса"
                      onChange={(v: number) => setRule(r.key, { wallet_id: v })}
                      options={options.wallets.map((w) => ({ value: w.id, label: `${w.label} (${w.currency})` }))}
                    />
                  ),
                },
                {
                  title: '',
                  width: 48,
                  render: (_, r) => (
                    <Button
                      type="text"
                      danger
                      aria-label="Удалить правило"
                      icon={<DeleteOutlined />}
                      onClick={() => patch({ rules: data.rules.filter((_, i) => i !== r.key) })}
                    />
                  ),
                },
              ]}
            />
            <Button
              icon={<PlusOutlined />}
              style={{ marginTop: 8 }}
              onClick={() => patch({ rules: [...data.rules, { payment_type: '', payment_purpose: '', wallet_id: null }] })}
            >
              Добавить правило
            </Button>
          </div>

          <div>
            <Typography.Title level={5}>Карточка подтверждения</Typography.Title>
            <Typography.Paragraph type="secondary">
              Подтвердить поступление могут только эти пользователи. Если выбрана группа — карточка уходит в группу,
              иначе каждому в личку.
            </Typography.Paragraph>
            <UserPicker
              value={data.confirmer_user_ids}
              onChange={(v) => patch({ confirmer_user_ids: v })}
              options={options.users}
            />
            <Select
              style={{ width: 320, marginTop: 8 }}
              allowClear
              placeholder="Telegram-группа (необязательно)"
              value={data.card_telegram_chat_id ?? undefined}
              onChange={(v) => patch({ card_telegram_chat_id: v ?? null })}
              options={options.telegram_chats.map((c) => ({ value: c.id, label: c.name }))}
            />
          </div>

          <div>
            <Typography.Title level={5}>Предупреждения</Typography.Title>
            <Typography.Paragraph type="secondary">
              Если поступление не подтверждено, предупреждение приходит через N дней и повторяется каждые M дней.
            </Typography.Paragraph>
            <UserPicker
              value={data.alert_recipient_user_ids}
              onChange={(v) => patch({ alert_recipient_user_ids: v })}
              options={options.users}
            />
            <Select
              style={{ width: 320, marginTop: 8 }}
              allowClear
              placeholder="Telegram-группа (необязательно)"
              value={data.alert_telegram_chat_id ?? undefined}
              onChange={(v) => patch({ alert_telegram_chat_id: v ?? null })}
              options={options.telegram_chats.map((c) => ({ value: c.id, label: c.name }))}
            />
            <Space wrap style={{ marginTop: 12 }}>
              <InputNumber
                min={1}
                max={365}
                value={data.alert_after_days}
                onChange={(v) => patch({ alert_after_days: v ?? 3 })}
                addonBefore="Через"
                addonAfter="дн."
              />
              <InputNumber
                min={1}
                max={365}
                value={data.alert_repeat_every_days}
                onChange={(v) => patch({ alert_repeat_every_days: v ?? 1 })}
                addonBefore="Повторять каждые"
                addonAfter="дн."
              />
              <InputNumber
                min={0}
                max={23}
                value={data.alert_hour}
                onChange={(v) => patch({ alert_hour: v ?? 9 })}
                addonBefore="В"
                addonAfter=":00 Ташкент"
              />
            </Space>
          </div>

          <Button type="primary" onClick={() => void save()} loading={saving}>
            Сохранить
          </Button>
        </Space>
      ) : null}
    </Card>
  )
}
