import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Checkbox, Divider, Input, InputNumber, Select, Skeleton, Space, Tabs, Typography, message } from 'antd'
import { ArrowLeftOutlined, PlusOutlined, DeleteOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import {
  getRequestApprovalConfig,
  updateRequestApprovalConfig,
  type RequestApprovalConfigPaymentTypeItem,
  type RequestApprovalConfigResponse,
  type RequestApprovalConfigUpdatePayload,
  type RequestApprovalConfigStepItem,
} from '../../lib/api'
import { labelBlockAboveField } from '../formSpacing'

const PAYMENT_TYPES = ['Наличные', 'Перечисление', 'Пополнение', 'Платежная карта'] as const
type PaymentType = (typeof PAYMENT_TYPES)[number]

const STEP_TYPES: Array<{ value: string; label: string }> = [
  { value: 'serial', label: 'serial' },
  { value: 'payment', label: 'payment' },
]
const PAYMENT_ACTION_MODES: Array<{ value: 'callback' | 'webapp'; label: string }> = [
  { value: 'callback', label: 'callback' },
  { value: 'webapp', label: 'webapp' },
]

function emptyStep(step: number): RequestApprovalConfigStepItem {
  return {
    step,
    step_type: 'serial',
    is_enabled: true,
    approver_user_ids: [],
    payment_action_mode: 'callback',
    payment_webapp_url: '',
  }
}

function normalizeConfig(resp: RequestApprovalConfigResponse): RequestApprovalConfigResponse {
  const map = new Map(resp.payment_types.map((p) => [p.payment_type, p]))
  const normalizedPaymentTypes: RequestApprovalConfigPaymentTypeItem[] = PAYMENT_TYPES.map((pt) => {
    const row = map.get(pt)
    return (
      row ?? {
        payment_type: pt,
        is_enabled: false,
        steps: [],
      }
    )
  })

  return { ...resp, payment_types: normalizedPaymentTypes }
}

export function RequestApprovalConfigPage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [data, setData] = useState<RequestApprovalConfigResponse | null>(null)
  const [activeTab, setActiveTab] = useState<string>(PAYMENT_TYPES[0])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setError(null)
      try {
        const cfg = await getRequestApprovalConfig()
        if (!cancelled) setData(normalizeConfig(cfg))
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Ошибка загрузки конфигурации')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const approverOptions = useMemo(() => {
    return (data?.approver_candidates ?? []).map((u) => ({ label: u.username, value: u.id }))
  }, [data])

  const paymentTypeRow = (pt: string) => data?.payment_types.find((x) => x.payment_type === pt) ?? null

  const updatePaymentType = (pt: string, patch: Partial<RequestApprovalConfigPaymentTypeItem>) => {
    setData((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        payment_types: prev.payment_types.map((x) => (x.payment_type === pt ? { ...x, ...patch } : x)),
      }
    })
  }

  const updateStep = (pt: string, idx: number, patch: Partial<RequestApprovalConfigStepItem>) => {
    setData((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        payment_types: prev.payment_types.map((p) => {
          if (p.payment_type !== pt) return p
          const nextSteps = p.steps.map((s, i) => (i === idx ? { ...s, ...patch } : s))
          return { ...p, steps: nextSteps }
        }),
      }
    })
  }

  const addStep = (pt: string) => {
    setData((prev) => {
      if (!prev) return prev
      const cur = paymentTypeRow(pt)
      const maxStep = cur?.steps.reduce((acc, s) => Math.max(acc, s.step), 0) ?? 0
      const next = maxStep + 1
      return {
        ...prev,
        payment_types: prev.payment_types.map((p) => (p.payment_type === pt ? { ...p, steps: [...p.steps, emptyStep(next)] } : p)),
      }
    })
  }

  const removeStep = (pt: string, idx: number) => {
    setData((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        payment_types: prev.payment_types.map((p) => (p.payment_type === pt ? { ...p, steps: p.steps.filter((_, i) => i !== idx) } : p)),
      }
    })
  }

  const save = async () => {
    if (!data) return
    setSaving(true)
    setError(null)
    try {
      const payload: RequestApprovalConfigUpdatePayload = {
        payment_types: data.payment_types.map((pt) => ({
          payment_type: pt.payment_type,
          is_enabled: pt.is_enabled,
          steps: pt.steps.map((s) => ({
            step: s.step,
            step_type: s.step_type,
            is_enabled: s.is_enabled,
            approver_user_ids: s.approver_user_ids,
            payment_action_mode: s.payment_action_mode ?? 'callback',
            payment_webapp_url: s.payment_webapp_url ?? '',
          })),
        })),
      }

      setData(normalizeConfig(await updateRequestApprovalConfig(payload)))
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
        Настройка этапов согласования
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        Укажите для каждого типа оплаты шаги и approver-ов, которые согласуют заявку.
      </Typography.Paragraph>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        Параметры Telegram и n8n для заявок настраиваются в разделе{' '}
        <Button type="link" onClick={() => navigate('/settings/tenant-integration-config')} style={{ padding: 0, height: 'auto' }}>
          Интеграции tenant
        </Button>
        .
      </Typography.Paragraph>

      <Divider />

      {loading ? <Skeleton active /> : null}
      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} /> : null}

      {!loading && data ? (
        <>
          <Space direction="vertical" size={12} style={{ display: 'flex' }}>
            <Typography.Text strong style={labelBlockAboveField}>
              Типы оплаты
            </Typography.Text>
            <Space wrap>
              {data.payment_types.map((pt) => (
                <Checkbox
                  key={pt.payment_type}
                  checked={pt.is_enabled}
                  onChange={(e) => updatePaymentType(pt.payment_type, { is_enabled: e.target.checked })}
                >
                  {pt.payment_type}
                </Checkbox>
              ))}
            </Space>
          </Space>

          <Tabs
            activeKey={activeTab}
            onChange={setActiveTab}
            items={data.payment_types.map((pt) => ({
              key: pt.payment_type,
              label: pt.payment_type,
              children: (
                <Space direction="vertical" size={16} style={{ display: 'flex' }}>
                  {!pt.is_enabled ? (
                    <Alert type="warning" showIcon message="Тип оплаты выключен." />
                  ) : null}

                  <Space direction="vertical" size={12} style={{ display: 'flex' }}>
                    <Typography.Text strong style={labelBlockAboveField}>
                      Шаги согласования
                    </Typography.Text>

                    {pt.steps.length === 0 ? (
                      <Alert type="info" showIcon message="Шаги не настроены." />
                    ) : null}

                    {pt.steps
                      .slice()
                      .sort((a, b) => a.step - b.step)
                      .map((step, idxInSorted) => {
                        // map index back to actual index
                        const actualIdx = pt.steps.findIndex((s) => s.step === step.step && s.step_type === step.step_type)
                        const idx = actualIdx >= 0 ? actualIdx : idxInSorted

                        return (
                          <Card key={`${pt.payment_type}:${step.step}:${step.step_type}`} size="small" type="inner">
                            <Space direction="vertical" size={10} style={{ display: 'flex' }}>
                              <Space wrap align="start">
                                <div>
                                  <Typography.Text strong>Шаг</Typography.Text>
                                  <div style={{ height: 8 }} />
                                  <InputNumber
                                    value={step.step}
                                    min={1}
                                    onChange={(v) => updateStep(pt.payment_type, idx, { step: Number(v) })}
                                  />
                                </div>

                                <div>
                                  <Typography.Text strong>Тип шага</Typography.Text>
                                  <div style={{ height: 8 }} />
                                  <Select
                                    value={step.step_type}
                                    onChange={(v) => updateStep(pt.payment_type, idx, { step_type: v })}
                                    options={STEP_TYPES}
                                    style={{ width: 180 }}
                                  />
                                </div>

                                <div>
                                  <Typography.Text strong>Активен</Typography.Text>
                                  <div style={{ height: 8 }} />
                                  <Checkbox
                                    checked={step.is_enabled}
                                    onChange={(e) => updateStep(pt.payment_type, idx, { is_enabled: e.target.checked })}
                                  />
                                </div>

                                <div>
                                  <Button
                                    danger
                                    icon={<DeleteOutlined />}
                                    onClick={() => removeStep(pt.payment_type, idx)}
                                  >
                                    Удалить
                                  </Button>
                                </div>
                              </Space>

                              <div>
                                <Typography.Text strong style={labelBlockAboveField}>
                                  Approver-ы для шага
                                </Typography.Text>
                                <div style={{ height: 8 }} />
                                <Select
                                  mode="multiple"
                                  value={step.approver_user_ids}
                                  onChange={(v) => updateStep(pt.payment_type, idx, { approver_user_ids: v as number[] })}
                                  options={approverOptions}
                                  placeholder="Выберите approver-ов"
                                  style={{ width: '100%' }}
                                />
                              </div>
                              {step.step_type === 'payment' ? (
                                <>
                                  <div>
                                    <Typography.Text strong style={labelBlockAboveField}>
                                      Режим кнопки Выплатить
                                    </Typography.Text>
                                    <div style={{ height: 8 }} />
                                    <Select
                                      value={step.payment_action_mode ?? 'callback'}
                                      onChange={(v) =>
                                        updateStep(pt.payment_type, idx, {
                                          payment_action_mode: v as 'callback' | 'webapp',
                                        })
                                      }
                                      options={PAYMENT_ACTION_MODES}
                                      style={{ width: 220 }}
                                    />
                                  </div>
                                  {(step.payment_action_mode ?? 'callback') === 'webapp' ? (
                                    <div>
                                      <Typography.Text strong style={labelBlockAboveField}>
                                        Ссылка WebApp
                                      </Typography.Text>
                                      <div style={{ height: 8 }} />
                                      <Input
                                        value={step.payment_webapp_url ?? ''}
                                        onChange={(e) =>
                                          updateStep(pt.payment_type, idx, {
                                            payment_webapp_url: e.target.value,
                                          })
                                        }
                                        placeholder="https://t.me/ВашБот/ИмяПриложения (добавится startapp с id одобрения)"
                                      />
                                    </div>
                                  ) : null}
                                </>
                              ) : null}
                            </Space>
                          </Card>
                        )
                      })}

                    <Button icon={<PlusOutlined />} onClick={() => addStep(pt.payment_type)} disabled={!pt.is_enabled}>
                      Добавить шаг
                    </Button>
                  </Space>
                </Space>
              ),
            }))}
          />

          <Divider />

          <Button type="primary" onClick={() => void save()} loading={saving} disabled={loading}>
            Сохранить
          </Button>
        </>
      ) : null}
    </Card>
  )
}

