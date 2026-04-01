import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Checkbox, Divider, Input, InputNumber, Select, Space, Typography, message } from 'antd'
import { ArrowLeftOutlined, PlusOutlined, SaveOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import {
  getAutoRequestConfig,
  updateAutoRequestConfig,
  type AutoRequestTemplateItem,
  type AutoRequestConfigResponse,
} from '../../lib/api'
import { labelBlockAboveField } from '../formSpacing'

const PAYMENT_TYPES = ['Наличные', 'Перечисление', 'Пополнение', 'Платежная карта'] as const

function emptyTemplate(): AutoRequestTemplateItem {
  return {
    is_enabled: false,
    name: '',
    payment_type: 'Наличные',
    day_of_month: 1,
    title_template: '',
    description_template: '',
    company_payer: '',
    amount: null,
    currency: 'UZS',
    urgency: 'Обычно',
    payment_purpose: '',
    vendor_ref_id: null,
    requester_id: 0,
  }
}

export function AutoRequestsConfigPage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<AutoRequestConfigResponse | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setError(null)
      try {
        const resp = await getAutoRequestConfig()
        if (!cancelled) setData(resp)
      } catch (e: any) {
        if (!cancelled) setError(e?.message || 'Ошибка загрузки')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const requesterOptions = useMemo(
    () => (data?.requester_candidates || []).map((u) => ({ value: u.id, label: u.username })),
    [data],
  )

  const updateRow = (idx: number, patch: Partial<AutoRequestTemplateItem>) => {
    setData((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        templates: prev.templates.map((row, i) => (i === idx ? { ...row, ...patch } : row)),
      }
    })
  }

  const addTemplate = () => {
    setData((prev) => {
      if (!prev) return prev
      return { ...prev, templates: [...prev.templates, emptyTemplate()] }
    })
  }

  const removeTemplate = (idx: number) => {
    setData((prev) => {
      if (!prev) return prev
      return { ...prev, templates: prev.templates.filter((_, i) => i !== idx) }
    })
  }

  const save = async () => {
    if (!data) return
    setSaving(true)
    setError(null)
    try {
      const payload = {
        templates: data.templates.map((row) => ({
          id: row.id,
          is_enabled: row.is_enabled,
          name: String(row.name || '').trim(),
          payment_type: row.payment_type,
          day_of_month: row.day_of_month || 1,
          title_template: String(row.title_template || ''),
          description_template: String(row.description_template || ''),
          company_payer: String(row.company_payer || ''),
          amount: row.amount == null || row.amount === '' ? null : row.amount,
          currency: row.currency || 'UZS',
          urgency: row.urgency || 'Обычно',
          payment_purpose: String(row.payment_purpose || ''),
          vendor_ref_id: row.vendor_ref_id ?? null,
          requester_id: row.requester_id,
        })),
      }
      setData(await updateAutoRequestConfig(payload))
      message.success('Сохранено')
    } catch (e: any) {
      setError(e?.message || 'Ошибка сохранения')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card>
      <Button type="link" icon={<ArrowLeftOutlined />} onClick={() => navigate('/requests')} style={{ padding: 0 }}>
        Назад к заявкам
      </Button>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Автозаявки
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        Автоматическое создание заявок в выбранный день каждого месяца по шаблону.
      </Typography.Paragraph>
      <Divider />
      {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} /> : null}
      {loading ? (
        <Typography.Text type="secondary">Загрузка...</Typography.Text>
      ) : (
        <Space direction="vertical" size={12} style={{ display: 'flex' }}>
          <Button icon={<PlusOutlined />} onClick={addTemplate}>
            Добавить автозаявку
          </Button>
          {(data?.templates || []).map((row, idx) => (
            <Card key={row.id ?? `new-${idx}`} size="small">
              <Space direction="vertical" size={10} style={{ display: 'flex' }}>
                <Space align="center" wrap>
                  <Typography.Text strong>Шаблон #{idx + 1}</Typography.Text>
                  <Checkbox checked={row.is_enabled} onChange={(e) => updateRow(idx, { is_enabled: e.target.checked })}>
                    Активно
                  </Checkbox>
                  <Button danger onClick={() => removeTemplate(idx)}>
                    Удалить
                  </Button>
                </Space>
                <Input
                  placeholder="Название шаблона"
                  value={row.name}
                  onChange={(e) => updateRow(idx, { name: e.target.value })}
                />
                <Space wrap size={12}>
                  <Select
                    style={{ width: 180 }}
                    value={row.payment_type}
                    onChange={(v) => updateRow(idx, { payment_type: v })}
                    options={PAYMENT_TYPES.map((v) => ({ value: v, label: v }))}
                  />
                  <InputNumber
                    min={1}
                    max={31}
                    value={row.day_of_month}
                    onChange={(v) => updateRow(idx, { day_of_month: typeof v === 'number' ? v : 1 })}
                    addonBefore="День месяца"
                  />
                  <Select
                    style={{ width: 220 }}
                    value={row.requester_id || undefined}
                    placeholder="Заявитель"
                    onChange={(v) => updateRow(idx, { requester_id: v })}
                    options={requesterOptions}
                    showSearch
                    optionFilterProp="label"
                  />
                </Space>
                <Input
                  placeholder="Заголовок (поддержка токенов {{billing_month_ru}}, {{billing_month:%B %Y}}, {{now:%d.%m.%Y}})"
                  value={row.title_template}
                  onChange={(e) => updateRow(idx, { title_template: e.target.value })}
                />
                <Input.TextArea
                  rows={3}
                  placeholder="Описание шаблона с токенами даты"
                  value={row.description_template}
                  onChange={(e) => updateRow(idx, { description_template: e.target.value })}
                />
                <Space wrap size={12}>
                  <Input
                    style={{ width: 220 }}
                    placeholder="Компания-плательщик"
                    value={row.company_payer}
                    onChange={(e) => updateRow(idx, { company_payer: e.target.value })}
                  />
                  <InputNumber
                    style={{ width: 150 }}
                    min={0}
                    placeholder="Сумма"
                    value={row.amount == null ? undefined : Number(row.amount)}
                    onChange={(v) => updateRow(idx, { amount: v == null ? null : String(v) })}
                  />
                  <Select
                    style={{ width: 120 }}
                    value={row.currency}
                    onChange={(v) => updateRow(idx, { currency: v })}
                    options={['UZS', 'USD', 'EUR', 'RUB'].map((v) => ({ value: v, label: v }))}
                  />
                  <Select
                    style={{ width: 140 }}
                    value={row.urgency}
                    onChange={(v) => updateRow(idx, { urgency: v })}
                    options={['Низко', 'Обычно', 'Срочно'].map((v) => ({ value: v, label: v }))}
                  />
                </Space>
                <Input
                  placeholder="Назначение платежа"
                  value={row.payment_purpose}
                  onChange={(e) => updateRow(idx, { payment_purpose: e.target.value })}
                />
                <Typography.Text type="secondary" style={labelBlockAboveField}>
                  Последний запуск: {row.last_run_month || 'еще не запускалось'}
                </Typography.Text>
              </Space>
            </Card>
          ))}
          <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={save}>
            Сохранить
          </Button>
        </Space>
      )}
    </Card>
  )
}
