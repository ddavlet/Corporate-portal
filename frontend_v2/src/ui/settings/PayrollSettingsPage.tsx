import { useEffect, useState } from 'react'
import { Button, Card, Checkbox, Form, Input, InputNumber, Radio, Typography, message } from 'antd'
import {
  getTenantPayrollDocIdFormat,
  getTenantPayrollSettings,
  updateTenantPayrollDocIdFormat,
  updateTenantPayrollSettings,
  type TenantPayrollSettingsDto,
} from '../../lib/api'

function previewPayrollDocId(prefix: string, digitWidth: number, sampleNumeric: number): string {
  const w = Number.isFinite(digitWidth) ? Math.min(32, Math.max(1, Math.floor(digitWidth))) : 9
  const core = String(Math.trunc(sampleNumeric)).padStart(w, '0')
  return `${prefix}${core}`
}

function PayrollDocIdFormatSection() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [hidden, setHidden] = useState(false)
  const [form] = Form.useForm<{
    payroll_doc_id_prefix: string
    payroll_doc_id_digit_width: number
  }>()
  const prefixWatch = Form.useWatch('payroll_doc_id_prefix', form)
  const widthWatch = Form.useWatch('payroll_doc_id_digit_width', form)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        const data = await getTenantPayrollDocIdFormat()
        if (cancelled) return
        form.setFieldsValue({
          payroll_doc_id_prefix: data.payroll_doc_id_prefix ?? '',
          payroll_doc_id_digit_width: data.payroll_doc_id_digit_width ?? 9,
        })
        setHidden(false)
      } catch {
        if (!cancelled) setHidden(true)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [form])

  if (hidden) return null

  const p = typeof prefixWatch === 'string' ? prefixWatch : ''
  const dw = typeof widthWatch === 'number' ? widthWatch : 9
  const preview = previewPayrollDocId(p, dw, 459)

  const onSave = async () => {
    try {
      const v = await form.validateFields()
      setSaving(true)
      await updateTenantPayrollDocIdFormat({
        payroll_doc_id_prefix: v.payroll_doc_id_prefix.trim(),
        payroll_doc_id_digit_width: v.payroll_doc_id_digit_width,
      })
      message.success('Сохранено')
    } catch (e: unknown) {
      if (e && typeof e === 'object' && 'errorFields' in e) return
      message.error(e instanceof Error ? e.message : 'Ошибка сохранения')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card title="Формат номера ведомости (doc_id)" style={{ marginBottom: 16 }} loading={loading}>
      <Typography.Paragraph type="secondary">
        Привязка заявки типа «Начисление ЗП»: можно ввести короткий номер (например{' '}
        <Typography.Text code>459</Typography.Text>), система найдёт документ по полному <Typography.Text code>doc_id</Typography.Text>.
      </Typography.Paragraph>
      <Form form={form} layout="vertical" disabled={loading}>
        <Form.Item
          label="Префикс перед номером"
          name="payroll_doc_id_prefix"
          rules={[{ max: 32, message: 'Не длиннее 32 символов' }]}
        >
          <Input placeholder="Например: 1- или пусто" allowClear />
        </Form.Item>
        <Form.Item
          label="Числовая часть: знаков всего"
          name="payroll_doc_id_digit_width"
          rules={[{ required: true }]}
        >
          <InputNumber min={1} max={32} style={{ width: '100%' }} />
        </Form.Item>
      </Form>
      <Typography.Paragraph style={{ marginBottom: 16 }}>
        Пример: ввод <Typography.Text code>459</Typography.Text> совпадает с ведомостью{' '}
        <Typography.Text code>{preview}</Typography.Text>.
      </Typography.Paragraph>
      <Button type="primary" onClick={() => void onSave()} loading={saving} disabled={loading}>
        Сохранить формат
      </Button>
    </Card>
  )
}

function PayrollSettingsSection() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [hidden, setHidden] = useState(false)
  const [enabled, setEnabled] = useState(false)
  const [payoutMode, setPayoutMode] = useState<'portal' | 'legacy'>('legacy')

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      try {
        const data = await getTenantPayrollSettings()
        if (cancelled) return
        setEnabled(data.create_payment_request_on_payroll_accrual)
        setPayoutMode(data.payroll_payout_mode ?? 'legacy')
        setHidden(false)
      } catch {
        if (!cancelled) setHidden(true)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  if (hidden) return null

  const save = async (patch: Partial<TenantPayrollSettingsDto>, revert: () => void) => {
    setSaving(true)
    try {
      await updateTenantPayrollSettings({
        create_payment_request_on_payroll_accrual: enabled,
        payroll_payout_mode: payoutMode,
        ...patch,
      })
      message.success('Сохранено')
    } catch (e: unknown) {
      revert()
      message.error(e instanceof Error ? e.message : 'Ошибка сохранения')
    } finally {
      setSaving(false)
    }
  }

  const onToggle = async (checked: boolean) => {
    const prev = enabled
    setEnabled(checked)
    await save({ create_payment_request_on_payroll_accrual: checked }, () => setEnabled(prev))
  }

  const onModeChange = async (mode: 'portal' | 'legacy') => {
    const prev = payoutMode
    setPayoutMode(mode)
    await save({ payroll_payout_mode: mode }, () => setPayoutMode(prev))
  }

  return (
    <Card title="Настройки начислений" style={{ marginBottom: 16 }} loading={loading}>
      <Checkbox checked={enabled} disabled={loading || saving} onChange={(e) => void onToggle(e.target.checked)}>
        Создавать заявку на оплату при создании начисления
      </Checkbox>
      <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
        Применяется и к начислениям, созданным в портале, и к загруженным через n8n — на сумму всего документа
        создаётся одна заявка.
      </Typography.Paragraph>
      <Typography.Paragraph style={{ marginTop: 16, marginBottom: 8 }}>Выплата ЗП</Typography.Paragraph>
      <Radio.Group
        disabled={loading || saving}
        value={payoutMode}
        onChange={(e) => void onModeChange(e.target.value)}
      >
        <Radio value="portal" style={{ display: 'block', marginBottom: 8 }}>
          Через портал (частичные выплаты из кассы, заявка закрывается автоматически)
        </Radio>
        <Radio value="legacy" style={{ display: 'block' }}>
          Как раньше (оплата подтверждается в Telegram)
        </Radio>
      </Radio.Group>
      <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
        Режим фиксируется в начислении в момент принятия; уже принятые начисления не меняются.
      </Typography.Paragraph>
    </Card>
  )
}

export function PayrollSettingsPage() {
  return (
    <>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Начисления ЗП
      </Typography.Title>
      <PayrollDocIdFormatSection />
      <PayrollSettingsSection />
    </>
  )
}
