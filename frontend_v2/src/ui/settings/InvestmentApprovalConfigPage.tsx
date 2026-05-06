import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Checkbox, Divider, InputNumber, Select, Skeleton, Space, Typography, message } from 'antd'
import { ArrowLeftOutlined, DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'

import {
  getInvestmentApprovalConfig,
  updateInvestmentApprovalConfig,
  type InvestmentApprovalConfigResponse,
  type InvestmentApprovalConfigStepItem,
} from '../../lib/api'
import { labelBlockAboveField } from '../formSpacing'

function emptyStep(step: number): InvestmentApprovalConfigStepItem {
  return { step, step_type: 'serial', is_enabled: true, payment_chat_id: null, approver_user_ids: [] }
}

export function InvestmentApprovalConfigPage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<InvestmentApprovalConfigResponse | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setError(null)
      try {
        const cfg = await getInvestmentApprovalConfig()
        if (!cancelled) setData(cfg)
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

  const approverOptions = useMemo(
    () => (data?.approver_candidates ?? []).map((u) => ({ value: u.id, label: u.username })),
    [data],
  )

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
        is_enabled: data.is_enabled,
        steps: data.steps.map((s) => ({
          step: s.step,
          step_type: s.step_type ?? 'serial',
          is_enabled: s.is_enabled,
          payment_chat_id: s.step_type === 'confirmation' ? (s.payment_chat_id ?? null) : null,
          approver_user_ids: s.approver_user_ids,
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

  return (
    <Card>
      <Button type="link" icon={<ArrowLeftOutlined />} onClick={() => navigate('/settings')} style={{ padding: 0 }}>
        Назад к настройкам
      </Button>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Инвестиции - этапы согласования
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        Настройте шаги подтверждения новой выплаты по инвестициям в Telegram.
      </Typography.Paragraph>

      <Divider />
      {loading ? <Skeleton active /> : null}
      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} /> : null}

      {!loading && data ? (
        <Space direction="vertical" size={12} style={{ display: 'flex' }}>
          <Checkbox checked={data.is_enabled} onChange={(e) => setData({ ...data, is_enabled: e.target.checked })}>
            Включить согласование выплат по инвестициям
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
                        style={{ width: 180 }}
                        onChange={(v) =>
                          updateStep(idx, {
                            step_type: v as 'serial' | 'confirmation',
                            payment_chat_id: v === 'confirmation' ? (step.payment_chat_id ?? null) : null,
                          })
                        }
                        options={[
                          { value: 'serial', label: 'serial (проверка)' },
                          { value: 'confirmation', label: 'confirmation (подтверждение получения)' },
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
                    <Select
                      mode="multiple"
                      value={step.approver_user_ids}
                      onChange={(v) => updateStep(idx, { approver_user_ids: v as number[] })}
                      options={approverOptions}
                      style={{ width: '100%' }}
                    />
                  </div>
                  {step.step_type === 'confirmation' ? (
                    <div>
                      <Typography.Text strong style={labelBlockAboveField}>
                        Chat ID для этапа оплаты
                      </Typography.Text>
                      <InputNumber
                        style={{ width: '100%' }}
                        value={step.payment_chat_id ?? undefined}
                        onChange={(v) => updateStep(idx, { payment_chat_id: v == null ? null : Number(v) })}
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
