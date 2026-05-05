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

function emptyStep(step: number): RequestApprovalConfigStepItem {
  return {
    step,
    step_type: 'serial',
    is_enabled: true,
    approver_user_ids: [],
    payment_action_mode: 'callback',
    payment_webapp_url: '',
    payment_chat_id: null,
  }
}

function emptyPurposeException(): NonNullable<RequestApprovalConfigPaymentTypeItem['purpose_exceptions']>[number] {
  return {
    name: '',
    is_enabled: true,
    payment_purpose_ids: [],
    steps: [emptyStep(1)],
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
        payment_action_mode_options: ['callback', 'webapp'],
        request_not_required_field_options: [],
        request_not_required_rules: [],
        purpose_candidates: [],
        purpose_exceptions: [],
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

  const updatePurposeException = (
    pt: string,
    excIdx: number,
    patch: Partial<NonNullable<RequestApprovalConfigPaymentTypeItem['purpose_exceptions']>[number]>,
  ) => {
    setData((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        payment_types: prev.payment_types.map((p) => {
          if (p.payment_type !== pt) return p
          const next = [...(p.purpose_exceptions ?? [])]
          next[excIdx] = { ...next[excIdx], ...patch }
          return { ...p, purpose_exceptions: next }
        }),
      }
    })
  }

  const updatePurposeExceptionStep = (
    pt: string,
    excIdx: number,
    stepIdx: number,
    patch: Partial<RequestApprovalConfigStepItem>,
  ) => {
    setData((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        payment_types: prev.payment_types.map((p) => {
          if (p.payment_type !== pt) return p
          const exceptions = [...(p.purpose_exceptions ?? [])]
          const current = exceptions[excIdx]
          const steps = [...(current.steps ?? [])]
          steps[stepIdx] = { ...steps[stepIdx], ...patch }
          exceptions[excIdx] = { ...current, steps }
          return { ...p, purpose_exceptions: exceptions }
        }),
      }
    })
  }

  const addPurposeException = (pt: string) => {
    setData((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        payment_types: prev.payment_types.map((p) =>
          p.payment_type === pt ? { ...p, purpose_exceptions: [...(p.purpose_exceptions ?? []), emptyPurposeException()] } : p,
        ),
      }
    })
  }

  const addPurposeExceptionStep = (pt: string, excIdx: number) => {
    setData((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        payment_types: prev.payment_types.map((p) => {
          if (p.payment_type !== pt) return p
          const exceptions = [...(p.purpose_exceptions ?? [])]
          const current = exceptions[excIdx]
          const maxStep = (current.steps ?? []).reduce((acc, s) => Math.max(acc, s.step), 0)
          const next = maxStep + 1
          const steps = [...(current.steps ?? []), emptyStep(next)]
          exceptions[excIdx] = { ...current, steps }
          return { ...p, purpose_exceptions: exceptions }
        }),
      }
    })
  }

  const removePurposeException = (pt: string, excIdx: number) => {
    setData((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        payment_types: prev.payment_types.map((p) =>
          p.payment_type === pt
            ? { ...p, purpose_exceptions: (p.purpose_exceptions ?? []).filter((_, i) => i !== excIdx) }
            : p,
        ),
      }
    })
  }

  const updateRequestNotRequiredRules = (
    pt: string,
    updater: (rules: Array<{ field: string; operator?: 'eq' | string; value: string }>) => Array<{ field: string; operator?: 'eq' | string; value: string }>,
  ) => {
    setData((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        payment_types: prev.payment_types.map((p) => {
          if (p.payment_type !== pt) return p
          const current = p.request_not_required_rules ?? []
          return { ...p, request_not_required_rules: updater(current) }
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
          ...(data.is_tenant_admin
            ? {
                request_not_required_rules: (pt.request_not_required_rules ?? []).map((r) => ({
                  field: r.field,
                  operator: r.operator ?? 'eq',
                  value: r.value,
                })),
              }
            : {}),
          purpose_exceptions: (pt.purpose_exceptions ?? []).map((exc) => ({
            id: exc.id,
            name: exc.name ?? '',
            is_enabled: exc.is_enabled,
            payment_purpose_ids: exc.payment_purpose_ids ?? [],
            steps: (exc.steps ?? []).map((s) => ({
              step: s.step,
              step_type: s.step_type,
              is_enabled: s.is_enabled,
              approver_user_ids: s.approver_user_ids,
              payment_action_mode: s.payment_action_mode ?? 'callback',
              payment_webapp_url: s.payment_webapp_url ?? '',
              payment_chat_id: s.step_type === 'payment' ? s.payment_chat_id ?? null : null,
            })),
          })),
          steps: pt.steps.map((s) => ({
            step: s.step,
            step_type: s.step_type,
            is_enabled: s.is_enabled,
            approver_user_ids: s.approver_user_ids,
            payment_action_mode: s.payment_action_mode ?? 'callback',
            payment_webapp_url: s.payment_webapp_url ?? '',
            payment_chat_id: s.step_type === 'payment' ? s.payment_chat_id ?? null : null,
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
        URL шлюза сообщений и тексты карточек Telegram задаются в конфигурации деплоя (
        <Typography.Text code>MESSAGING_GATEWAY_*</Typography.Text>). В{' '}
        <Button type="link" onClick={() => navigate('/settings/tenant-integration-config')} style={{ padding: 0, height: 'auto' }}>
          интеграциях tenant
        </Button>{' '}
        — токен бота и связанные секреты.
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
                      Исключения обязательности заявки
                    </Typography.Text>
                    {data.is_tenant_admin ? null : (
                      <Alert
                        type="info"
                        showIcon
                        message="Управление исключениями доступно только admin."
                      />
                    )}
                    {(pt.request_not_required_rules ?? []).length === 0 ? (
                      <Alert type="info" showIcon message="Исключения не настроены. По умолчанию заявка обязательна." />
                    ) : null}
                    {(pt.request_not_required_rules ?? []).map((rule, ruleIdx) => (
                      <Space key={`${pt.payment_type}-rule-${ruleIdx}`} wrap align="start">
                        <Select
                          value={rule.field}
                          onChange={(value) =>
                            updateRequestNotRequiredRules(pt.payment_type, (rules) =>
                              rules.map((r, idx) => (idx === ruleIdx ? { ...r, field: value } : r)),
                            )
                          }
                          options={(pt.request_not_required_field_options ?? []).map((value) => ({ value, label: value }))}
                          style={{ width: 220 }}
                          disabled={!data.is_tenant_admin}
                        />
                        <Input
                          value={rule.value}
                          onChange={(e) =>
                            updateRequestNotRequiredRules(pt.payment_type, (rules) =>
                              rules.map((r, idx) => (idx === ruleIdx ? { ...r, value: e.target.value } : r)),
                            )
                          }
                          placeholder="Значение"
                          style={{ width: 260 }}
                          disabled={!data.is_tenant_admin}
                        />
                        <Button
                          danger
                          onClick={() =>
                            updateRequestNotRequiredRules(pt.payment_type, (rules) => rules.filter((_, idx) => idx !== ruleIdx))
                          }
                          disabled={!data.is_tenant_admin}
                        >
                          Удалить
                        </Button>
                      </Space>
                    ))}
                    <Button
                      onClick={() =>
                        updateRequestNotRequiredRules(pt.payment_type, (rules) => [
                          ...rules,
                          { field: (pt.request_not_required_field_options ?? [])[0] ?? '', operator: 'eq', value: '' },
                        ])
                      }
                      disabled={!data.is_tenant_admin}
                    >
                      Добавить исключение
                    </Button>
                  </Space>

                  <Space direction="vertical" size={12} style={{ display: 'flex' }}>
                    <Typography.Text strong style={labelBlockAboveField}>
                      Исключения этапов по назначению платежа
                    </Typography.Text>
                    {(pt.purpose_exceptions ?? []).length === 0 ? (
                      <Alert type="info" showIcon message="Исключения не настроены. Будут применяться базовые шаги ниже." />
                    ) : null}
                    {(pt.purpose_exceptions ?? []).map((exc, excIdx) => (
                      <Card key={`${pt.payment_type}-exc-${excIdx}`} size="small" type="inner">
                        <Space direction="vertical" size={10} style={{ display: 'flex' }}>
                          <Space wrap align="start">
                            <Input
                              value={exc.name ?? ''}
                              onChange={(e) => updatePurposeException(pt.payment_type, excIdx, { name: e.target.value })}
                              placeholder="Название исключения (опционально)"
                              style={{ width: 320 }}
                            />
                            <Checkbox
                              checked={exc.is_enabled}
                              onChange={(e) => updatePurposeException(pt.payment_type, excIdx, { is_enabled: e.target.checked })}
                            >
                              Активно
                            </Checkbox>
                            <Button danger onClick={() => removePurposeException(pt.payment_type, excIdx)}>
                              Удалить исключение
                            </Button>
                          </Space>
                          <Select
                            mode="multiple"
                            value={exc.payment_purpose_ids ?? []}
                            onChange={(v) => updatePurposeException(pt.payment_type, excIdx, { payment_purpose_ids: v as number[] })}
                            options={(pt.purpose_candidates ?? []).map((p) => ({ value: p.id, label: p.name }))}
                            placeholder="Выберите назначения платежа для исключения"
                            style={{ width: '100%' }}
                          />
                          {(exc.steps ?? []).map((step, stepIdx) => (
                            <Space key={`${pt.payment_type}-exc-${excIdx}-step-${stepIdx}`} wrap align="start">
                              <InputNumber
                                value={step.step}
                                min={1}
                                onChange={(v) => updatePurposeExceptionStep(pt.payment_type, excIdx, stepIdx, { step: Number(v) })}
                              />
                              <Select
                                value={step.step_type}
                                onChange={(v) => updatePurposeExceptionStep(pt.payment_type, excIdx, stepIdx, { step_type: v })}
                                options={STEP_TYPES}
                                style={{ width: 160 }}
                              />
                              <Select
                                mode="multiple"
                                value={step.approver_user_ids}
                                onChange={(v) =>
                                  updatePurposeExceptionStep(pt.payment_type, excIdx, stepIdx, { approver_user_ids: v as number[] })
                                }
                                options={approverOptions}
                                placeholder="Approver-ы"
                                style={{ width: 360 }}
                              />
                              {step.step_type === 'payment' ? (
                                <InputNumber
                                  value={step.payment_chat_id ?? null}
                                  onChange={(v) =>
                                    updatePurposeExceptionStep(pt.payment_type, excIdx, stepIdx, {
                                      payment_chat_id: v === null || v === undefined ? null : Number(v),
                                    })
                                  }
                                  placeholder="Chat ID (например, -1001234567890)"
                                  style={{ width: 260 }}
                                  controls={false}
                                />
                              ) : null}
                            </Space>
                          ))}
                          <Button icon={<PlusOutlined />} onClick={() => addPurposeExceptionStep(pt.payment_type, excIdx)}>
                            Добавить шаг
                          </Button>
                        </Space>
                      </Card>
                    ))}
                    <Button onClick={() => addPurposeException(pt.payment_type)} disabled={!pt.is_enabled}>
                      Добавить исключение по назначениям
                    </Button>
                  </Space>

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
                                          payment_action_mode: v as RequestApprovalConfigStepItem['payment_action_mode'],
                                        })
                                      }
                                      options={(pt.payment_action_mode_options ?? ['callback', 'webapp']).map((mode) => ({
                                        value: mode,
                                        label: mode,
                                      }))}
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
                                  <div>
                                    <Typography.Text strong style={labelBlockAboveField}>
                                      Chat ID
                                    </Typography.Text>
                                    <div style={{ height: 8 }} />
                                    <InputNumber
                                      value={step.payment_chat_id ?? null}
                                      onChange={(v) =>
                                        updateStep(pt.payment_type, idx, {
                                          payment_chat_id: v === null || v === undefined ? null : Number(v),
                                        })
                                      }
                                      placeholder="Например, -1001234567890"
                                      style={{ width: 260 }}
                                      controls={false}
                                    />
                                    <div style={{ height: 4 }} />
                                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                                      Используется для уведомлений на этапе оплаты. Если пусто — берётся chat_id approver-а.
                                    </Typography.Text>
                                  </div>
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

