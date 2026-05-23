import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Checkbox, Divider, InputNumber, Select, Skeleton, Space, Typography, message } from 'antd'
import { ArrowLeftOutlined, DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'

import {
  getInvestmentApprovalConfig,
  listTelegramChats,
  updateInvestmentApprovalConfig,
  type InvestmentApprovalConfigResponse,
  type InvestmentApprovalConfigStepItem,
  type TenantTelegramChatDto,
} from '../../lib/api'
import { labelBlockAboveField } from '../formSpacing'

const DEFAULT_RETURN_TYPE_KEY = '__default__'
const DEFAULT_RECIPIENT_KEY = '__all__'

function emptyStep(step: number): InvestmentApprovalConfigStepItem {
  return { step, step_type: 'serial', is_enabled: true, telegram_chat_id: null, approver_user_ids: [] }
}

export function InvestmentApprovalConfigPage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<InvestmentApprovalConfigResponse | null>(null)
  const [returnTypeFilter, setReturnTypeFilter] = useState<string | null>(null)
  const [recipientFilter, setRecipientFilter] = useState<string | null>(null)
  const [tgChats, setTgChats] = useState<TenantTelegramChatDto[]>([])

  const load = useCallback(async (rt: string | null, rec: string | null) => {
    setLoading(true)
    setError(null)
    try {
      const cfg = await getInvestmentApprovalConfig(rt, rec)
      setData(cfg)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load(returnTypeFilter, recipientFilter)
  }, [load, returnTypeFilter, recipientFilter])

  useEffect(() => {
    void listTelegramChats().then(setTgChats).catch(() => setTgChats([]))
  }, [])

  const approverOptions = useMemo(
    () => (data?.approver_candidates ?? []).map((u) => ({ value: u.id, label: u.username })),
    [data],
  )

  const returnTypeSelectOptions = useMemo(() => {
    const choices = data?.return_type_choices ?? []
    return [
      { value: DEFAULT_RETURN_TYPE_KEY, label: 'По умолчанию (все типы без отдельной настройки)' },
      ...choices.map((c) => ({ value: c.value, label: c.label })),
    ]
  }, [data?.return_type_choices])

  const recipientSelectOptions = useMemo(() => {
    const choices = data?.recipient_choices ?? []
    return [
      { value: DEFAULT_RECIPIENT_KEY, label: 'Все получатели (в рамках выбранного типа)' },
      ...choices.map((c) => ({ value: c.value, label: c.label })),
    ]
  }, [data?.recipient_choices])

  const updateStep = (idx: number, patch: Partial<InvestmentApprovalConfigStepItem>) => {
    setData((prev) => {
      if (!prev) return prev
      const steps = prev.steps.map((s, i) => (i === idx ? { ...s, ...patch } : s))
      return { ...prev, steps }
    })
  }

  const addStep = () => {
    setData((prev) => {
      if (!prev) return prev
      const maxStep = prev.steps.reduce((acc, x) => Math.max(acc, x.step), 0)
      return { ...prev, steps: [...prev.steps, emptyStep(maxStep + 1)] }
    })
  }

  const removeStep = (idx: number) => {
    setData((prev) => {
      if (!prev) return prev
      return { ...prev, steps: prev.steps.filter((_, i) => i !== idx) }
    })
  }

  const save = async () => {
    if (!data) return
    setSaving(true)
    setError(null)
    try {
      const next = await updateInvestmentApprovalConfig({
        return_type: returnTypeFilter,
        recipient: recipientFilter,
        is_enabled: data.is_enabled,
        steps: data.steps.map((s) => ({
          step: s.step,
          step_type: s.step_type ?? 'serial',
          is_enabled: s.is_enabled,
          telegram_chat_id:
            s.step_type === 'confirmation' || s.step_type === 'notification' ? (s.telegram_chat_id ?? null) : null,
          approver_user_ids: s.approver_user_ids ?? [],
        })),
      })
      setData(next)
      message.success('Сохранено')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Ошибка сохранения')
    } finally {
      setSaving(false)
    }
  }

  const selectReturnValue = returnTypeFilter == null ? DEFAULT_RETURN_TYPE_KEY : returnTypeFilter
  const selectRecipientValue = recipientFilter == null ? DEFAULT_RECIPIENT_KEY : recipientFilter

  return (
    <Card>
      <Button type="link" icon={<ArrowLeftOutlined />} onClick={() => navigate('/settings')} style={{ padding: 0 }}>
        Назад к настройкам
      </Button>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Инвестиции - этапы согласования
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        Отдельная цепочка для комбинации типа выплаты и получателя: можно задать разные этапы и разные chat для
        confirmation (партнёр / инвестор). Если для пары «тип + получатель» нет записи, используется настройка «все
        получатели» для этого типа, затем глобальный дефолт.
      </Typography.Paragraph>

      <Divider />
      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} /> : null}

      <Space direction="vertical" size={12} style={{ display: 'flex', marginBottom: 12 }}>
        <div>
          <Typography.Text strong style={labelBlockAboveField}>
            Тип выплаты
          </Typography.Text>
          <Select
            style={{ width: '100%', maxWidth: 480 }}
            value={selectReturnValue}
            onChange={(v) => setReturnTypeFilter(v === DEFAULT_RETURN_TYPE_KEY ? null : String(v))}
            options={returnTypeSelectOptions}
            disabled={loading && !data}
          />
        </div>
        <div>
          <Typography.Text strong style={labelBlockAboveField}>
            Получатель выплаты
          </Typography.Text>
          <Select
            style={{ width: '100%', maxWidth: 480 }}
            value={selectRecipientValue}
            onChange={(v) => setRecipientFilter(v === DEFAULT_RECIPIENT_KEY ? null : String(v))}
            options={recipientSelectOptions}
            disabled={loading && !data}
          />
        </div>
      </Space>

      {loading && !data ? <Skeleton active /> : null}

      {!loading && data ? (
        <Space direction="vertical" size={12} style={{ display: 'flex' }}>
          <Checkbox checked={data.is_enabled} onChange={(e) => setData({ ...data, is_enabled: e.target.checked })}>
            Включить согласование для этой комбинации (тип + получатель)
          </Checkbox>
          {(data.steps ?? [])
            .slice()
            .sort((a, b) => a.step - b.step)
            .map((step, idx) => (
              <Card key={`step-${idx}-${step.step}`} size="small" type="inner">
                <Space direction="vertical" size={10} style={{ display: 'flex' }}>
                  <Space wrap align="start">
                    <div>
                      <Typography.Text strong style={labelBlockAboveField}>
                        Шаг
                      </Typography.Text>
                      <InputNumber min={1} value={step.step} onChange={(v) => updateStep(idx, { step: Number(v) })} />
                    </div>
                    <div>
                      <Typography.Text strong style={labelBlockAboveField}>
                        Тип этапа
                      </Typography.Text>
                      <Select
                        value={step.step_type ?? 'serial'}
                        style={{ width: 260 }}
                        onChange={(v) => {
                          const t = v as InvestmentApprovalConfigStepItem['step_type']
                          updateStep(idx, {
                            step_type: t,
                            telegram_chat_id:
                              t === 'confirmation' || t === 'notification' ? (step.telegram_chat_id ?? null) : null,
                          })
                        }}
                        options={[
                          { value: 'serial', label: 'serial (проверка)' },
                          { value: 'confirmation', label: 'confirmation (подтверждение получения)' },
                          {
                            value: 'notification',
                            label: 'notification (уведомление в chat, без кнопок, авто-подтверждение)',
                          },
                        ]}
                      />
                    </div>
                    <Checkbox checked={step.is_enabled} onChange={(e) => updateStep(idx, { is_enabled: e.target.checked })}>
                      Активен
                    </Checkbox>
                    <Button danger icon={<DeleteOutlined />} onClick={() => removeStep(idx)}>
                      Удалить
                    </Button>
                  </Space>
                  <div>
                    <Typography.Text strong style={labelBlockAboveField}>
                      Approver-ы
                    </Typography.Text>
                    <Typography.Paragraph type="secondary" style={{ marginBottom: 8, fontSize: 12 }}>
                      Для этапа notification список может быть пустым — в карточке будет указан автор выплаты; сообщение
                      уходит в chat ID ниже.
                    </Typography.Paragraph>
                    <Select
                      mode="multiple"
                      value={step.approver_user_ids}
                      onChange={(v) => updateStep(idx, { approver_user_ids: v as number[] })}
                      options={approverOptions}
                      style={{ width: '100%' }}
                    />
                  </div>
                  {step.step_type === 'confirmation' || step.step_type === 'notification' ? (
                    <div>
                      <Typography.Text strong style={labelBlockAboveField}>
                        {step.step_type === 'notification' ? 'Telegram-группа для уведомления' : 'Telegram-группа для этапа оплаты'}
                      </Typography.Text>
                      <Select
                        style={{ width: '100%' }}
                        allowClear
                        placeholder="Выберите Telegram-группу"
                        value={step.telegram_chat_id ?? undefined}
                        onChange={(v) => updateStep(idx, { telegram_chat_id: v ?? null })}
                        options={tgChats.map((c) => ({ value: c.id, label: c.name }))}
                      />
                    </div>
                  ) : null}
                </Space>
              </Card>
            ))}
          <Button icon={<PlusOutlined />} onClick={addStep}>
            Добавить шаг
          </Button>
          <Divider />
          <Button type="primary" onClick={() => void save()} loading={saving}>
            Сохранить
          </Button>
        </Space>
      ) : null}
    </Card>
  )
}
