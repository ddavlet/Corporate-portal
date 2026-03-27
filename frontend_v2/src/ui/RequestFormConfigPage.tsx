import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Checkbox, Divider, Input, Select, Skeleton, Space, Tabs, Typography, message } from 'antd'
import type { TabsProps } from 'antd'
import { PlusOutlined, SaveOutlined } from '@ant-design/icons'
import {
  getRequestFormConfig,
  updateRequestFormConfig,
  type RequestFormConfigPaymentTypeItem,
  type RequestFormConfigPurposeItem,
  type RequestFormConfigResponse,
} from '../lib/api'

const PAYMENT_TYPES = ['Наличные', 'Перечисление', 'Пополнение', 'Платежная карта'] as const

function normalizeConfig(resp: RequestFormConfigResponse): RequestFormConfigResponse {
  const existing = new Map(resp.payment_types.map((p) => [p.payment_type, p]))
  const normalized: RequestFormConfigPaymentTypeItem[] = PAYMENT_TYPES.map((pt) => {
    const row = existing.get(pt)
    return (
      row || {
        payment_type: pt,
        is_enabled: false,
        requester_ids: [],
        vendor_ids: [],
        payment_purposes: [],
      }
    )
  })
  return { ...resp, payment_types: normalized }
}

export function RequestFormConfigPage() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<string>(PAYMENT_TYPES[0])
  const [data, setData] = useState<RequestFormConfigResponse | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setError(null)
      try {
        const normalized = normalizeConfig(await getRequestFormConfig())
        if (!cancelled) setData(normalized)
      } catch (e: any) {
        if (!cancelled) setError(e?.message || 'Ошибка загрузки конфигурации')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const requesterOptions = useMemo(
    () => (data?.requester_candidates || []).map((u) => ({ label: u.username, value: u.id })),
    [data],
  )
  const vendorOptions = useMemo(
    () =>
      (data?.vendor_candidates || []).map((v) => ({
        label: v.account_number ? `${v.name} (${v.account_number})` : v.name,
        value: v.id,
      })),
    [data],
  )
  const categoryOptions = useMemo(() => (data?.category_candidates || []).map((c) => ({ label: c, value: c })), [data])

  const updatePaymentType = (paymentType: string, patch: Partial<RequestFormConfigPaymentTypeItem>) => {
    setData((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        payment_types: prev.payment_types.map((pt) => (pt.payment_type === paymentType ? { ...pt, ...patch } : pt)),
      }
    })
  }

  const addPurpose = (paymentType: string) => {
    setData((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        payment_types: prev.payment_types.map((pt) =>
          pt.payment_type === paymentType
            ? {
                ...pt,
                payment_purposes: [...pt.payment_purposes, { name: '', category: '', is_active: true }],
              }
            : pt,
        ),
      }
    })
  }

  const updatePurpose = (paymentType: string, idx: number, patch: Partial<RequestFormConfigPurposeItem>) => {
    setData((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        payment_types: prev.payment_types.map((pt) =>
          pt.payment_type === paymentType
            ? {
                ...pt,
                payment_purposes: pt.payment_purposes.map((p, i) => (i === idx ? { ...p, ...patch } : p)),
              }
            : pt,
        ),
      }
    })
  }

  const removePurpose = (paymentType: string, idx: number) => {
    setData((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        payment_types: prev.payment_types.map((pt) =>
          pt.payment_type === paymentType
            ? { ...pt, payment_purposes: pt.payment_purposes.filter((_, i) => i !== idx) }
            : pt,
        ),
      }
    })
  }

  const save = async () => {
    if (!data) return
    setSaving(true)
    setError(null)
    try {
      const payload = {
        payment_types: data.payment_types.map((pt) => ({
          payment_type: pt.payment_type,
          is_enabled: pt.is_enabled,
          requester_ids: pt.requester_ids,
          vendor_ids: pt.vendor_ids,
          payment_purposes: pt.payment_purposes
            .map((p) => ({
              name: String(p.name || '').trim(),
              category: String(p.category || '').trim(),
              is_active: p.is_active !== false,
            }))
            .filter((p) => p.name),
        })),
      }

      setData(normalizeConfig(await updateRequestFormConfig(payload)))
      message.success('Сохранено')
    } catch (e: any) {
      setError(e?.message || 'Ошибка сохранения')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Настройка формы заявки
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        Админ-конфигурация доступных типов оплаты, заявителей, поставщиков и назначений платежа.
      </Typography.Paragraph>

      <Divider />

      {loading ? <Skeleton active /> : null}
      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} /> : null}

      {!loading && data ? (
        <>
          <Space direction="vertical" size={12} style={{ display: 'flex' }}>
            <Typography.Text strong>Типы оплаты</Typography.Text>
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

          <Divider />

          <Tabs
            activeKey={activeTab}
            onChange={setActiveTab}
            items={data.payment_types.map((pt) => ({
              key: pt.payment_type,
              label: pt.payment_type,
              children: (
                <Space direction="vertical" size={16} style={{ display: 'flex' }}>
                  {!pt.is_enabled ? (
                    <Alert
                      type="warning"
                      showIcon
                      message="Тип оплаты выключен. Пользователи не смогут создать заявку с этим типом."
                    />
                  ) : null}

                  <div>
                    <Typography.Text strong>Заявители (requesters)</Typography.Text>
                    <div style={{ marginTop: 8 }}>
                      <Select
                        mode="multiple"
                        style={{ width: '100%' }}
                        placeholder="Выберите заявителей"
                        value={pt.requester_ids}
                        onChange={(value) => updatePaymentType(pt.payment_type, { requester_ids: value })}
                        options={requesterOptions}
                        optionFilterProp="label"
                        showSearch
                      />
                      <Typography.Paragraph type="secondary" style={{ marginTop: 6, marginBottom: 0 }}>
                        Если список пустой — по умолчанию разрешены все пользователи с ролью requester.
                      </Typography.Paragraph>
                    </div>
                  </div>

                  <div>
                    <Typography.Text strong>Поставщики (vendors)</Typography.Text>
                    <div style={{ marginTop: 8 }}>
                      <Select
                        mode="multiple"
                        style={{ width: '100%' }}
                        placeholder="Выберите поставщиков"
                        value={pt.vendor_ids}
                        onChange={(value) => updatePaymentType(pt.payment_type, { vendor_ids: value })}
                        options={vendorOptions}
                        optionFilterProp="label"
                        showSearch
                      />
                      <Typography.Paragraph type="secondary" style={{ marginTop: 6, marginBottom: 0 }}>
                        Если список пустой — ограничение не применяется (можно вводить любого поставщика).
                      </Typography.Paragraph>
                    </div>
                  </div>

                  <div>
                    <Space align="center" style={{ justifyContent: 'space-between', width: '100%' }}>
                      <Typography.Text strong>Назначения платежа (payment purpose)</Typography.Text>
                      <Button icon={<PlusOutlined />} onClick={() => addPurpose(pt.payment_type)}>
                        Добавить
                      </Button>
                    </Space>

                    {pt.payment_purposes.length === 0 ? (
                      <Alert
                        type="info"
                        showIcon
                        style={{ marginTop: 12 }}
                        message="Список пуст. Если вы добавите назначения, категория будет выставляться автоматически по выбранному назначению."
                      />
                    ) : null}

                    <Space direction="vertical" size={8} style={{ display: 'flex', marginTop: 12 }}>
                      {pt.payment_purposes.map((p, idx) => (
                        <Card key={`${pt.payment_type}:${idx}`} size="small">
                          <Space direction="vertical" size={8} style={{ display: 'flex' }}>
                            <Space wrap style={{ width: '100%' }}>
                              <Input
                                placeholder="Назначение платежа"
                                value={p.name}
                                onChange={(e) => updatePurpose(pt.payment_type, idx, { name: e.target.value })}
                                style={{ width: 360, maxWidth: '100%' }}
                              />
                              <Select
                                placeholder="Категория"
                                value={p.category || undefined}
                                onChange={(value) => updatePurpose(pt.payment_type, idx, { category: value })}
                                options={categoryOptions}
                                style={{ width: 280, maxWidth: '100%' }}
                                showSearch
                                optionFilterProp="label"
                              />
                              <Checkbox
                                checked={p.is_active !== false}
                                onChange={(e) => updatePurpose(pt.payment_type, idx, { is_active: e.target.checked })}
                              >
                                Активно
                              </Checkbox>
                              <Button danger onClick={() => removePurpose(pt.payment_type, idx)}>
                                Удалить
                              </Button>
                            </Space>
                            <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
                              При создании заявки категория будет выставлена автоматически по этому назначению.
                            </Typography.Paragraph>
                          </Space>
                        </Card>
                      ))}
                    </Space>
                  </div>
                </Space>
              ),
            }))}
          />

          <Divider />

          <Space>
            <Button type="primary" icon={<SaveOutlined />} onClick={save} loading={saving}>
              Сохранить
            </Button>
          </Space>
        </>
      ) : null}
    </Card>
  )
}

