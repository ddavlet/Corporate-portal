import { useEffect, useState } from 'react'
import { Alert, Button, Form, Input, InputNumber, Select, Skeleton, Typography } from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { getCashRegisters, getSettingsAccess, type CashRegisterDto } from '../../lib/api'
import {
  CashRegisterTransferSubmitError,
  cashRegisterLabel,
  submitCashRegisterTransfer,
} from '../../lib/cashRegisterTransfer'
import { useTgMainButton } from './useTgMainButton'

type FormValues = {
  from_wallet_id: number
  to_wallet_id: number
  amount: number
  note?: string
}

export function TgCashRegisterTransferPage() {
  const navigate = useNavigate()
  const [form] = Form.useForm<FormValues>()
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [registers, setRegisters] = useState<CashRegisterDto[]>([])
  const [requesterId, setRequesterId] = useState<number | null>(null)
  const fromWalletId = Form.useWatch('from_wallet_id', form)
  const toWalletId = Form.useWatch('to_wallet_id', form)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const [rows, access] = await Promise.all([getCashRegisters(), getSettingsAccess()])
        if (cancelled) return
        setRegisters(rows.filter((r) => r.is_active))
        setRequesterId(typeof access.user_id === 'number' ? access.user_id : null)
      } catch (e: unknown) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Не удалось загрузить список касс')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const fromRegister = registers.find((r) => r.id === fromWalletId) || null
  const toRegister = registers.find((r) => r.id === toWalletId) || null
  const currencyMismatch = Boolean(
    fromRegister && toRegister && fromRegister.currency !== toRegister.currency,
  )
  const fromOptions = registers
    .filter((r) => r.id !== toWalletId)
    .map((r) => ({ value: r.id, label: cashRegisterLabel(r) }))
  const toOptions = registers
    .filter((r) => r.id !== fromWalletId)
    .map((r) => ({ value: r.id, label: cashRegisterLabel(r) }))

  async function handleSubmit() {
    let values: FormValues
    try {
      values = await form.validateFields()
    } catch {
      return
    }
    const fromReg = registers.find((r) => r.id === values.from_wallet_id)
    const toReg = registers.find((r) => r.id === values.to_wallet_id)
    if (!fromReg || !toReg) return

    setSubmitting(true)
    setError(null)
    try {
      await submitCashRegisterTransfer({
        fromRegister: fromReg,
        toRegister: toReg,
        amount: values.amount,
        note: values.note,
        requesterId,
      })
      navigate('/tg/cash', { replace: true })
    } catch (err: unknown) {
      if (err instanceof CashRegisterTransferSubmitError) {
        setError(`Заявка №${err.requestId} создана, но не отправлена на согласование: ${err.message}`)
      } else {
        setError(err instanceof Error ? err.message : 'Не удалось создать заявку')
      }
    } finally {
      setSubmitting(false)
    }
  }

  useTgMainButton({
    text: 'Отправить',
    onClick: () => void handleSubmit(),
    loading: submitting,
    disabled: loading,
  })

  return (
    <div className="tg-cash-page" style={{ paddingBottom: 88 }}>
      <Button
        icon={<ArrowLeftOutlined />}
        size="large"
        onClick={() => navigate('/tg/cash')}
        style={{ marginBottom: 12, borderRadius: 12 }}
      >
        Назад
      </Button>

      <Typography.Title level={4} style={{ margin: '0 0 20px', fontWeight: 700 }}>
        Перевод между кассами
      </Typography.Title>

      {loading ? (
        <Skeleton active paragraph={{ rows: 5 }} />
      ) : (
        <Form form={form} layout="vertical">
          <Form.Item
            name="from_wallet_id"
            label="Из кассы"
            rules={[{ required: true, message: 'Выберите кассу-источник' }]}
          >
            <Select size="large" placeholder="Касса-источник" options={fromOptions} />
          </Form.Item>
          <Form.Item
            name="to_wallet_id"
            label="В кассу"
            dependencies={['from_wallet_id']}
            rules={[
              { required: true, message: 'Выберите кассу-назначение' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || value !== getFieldValue('from_wallet_id')) return Promise.resolve()
                  return Promise.reject(new Error('Касса-назначение должна отличаться от кассы-источника'))
                },
              }),
            ]}
          >
            <Select size="large" placeholder="Касса-назначение" options={toOptions} />
          </Form.Item>
          {currencyMismatch ? (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 16, borderRadius: 12 }}
              message="Кассы в разных валютах — уточните сумму зачисления в примечании."
            />
          ) : null}
          <Form.Item
            name="amount"
            label="Сумма"
            rules={[{ required: true, message: 'Укажите сумму' }]}
          >
            <InputNumber size="large" min={0.01} style={{ width: '100%' }} placeholder="0" />
          </Form.Item>
          <Form.Item name="note" label="Примечание">
            <Input.TextArea rows={2} maxLength={1000} size="large" />
          </Form.Item>
          {fromRegister && toRegister ? (
            <Typography.Text type="secondary">
              {cashRegisterLabel(fromRegister)} ({fromRegister.currency}) → {cashRegisterLabel(toRegister)} (
              {toRegister.currency})
            </Typography.Text>
          ) : null}
        </Form>
      )}

      {error ? (
        <Alert type="error" showIcon message={error} style={{ marginTop: 12, borderRadius: 12 }} />
      ) : null}
    </div>
  )
}
