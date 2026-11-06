import { useState } from 'react'
import { Alert, Button, Form, Input, InputNumber, Modal, Select, Typography, message } from 'antd'
import { SwapOutlined } from '@ant-design/icons'
import { getCashRegisters, getSettingsAccess, type CashRegisterDto } from '../lib/api'
import {
  CashRegisterTransferSubmitError,
  cashRegisterLabel,
  submitCashRegisterTransfer,
} from '../lib/cashRegisterTransfer'

type Props = {
  /** Перезагрузка списка операций после успешной отправки заявки. */
  onCreated?: () => void
}

type FormValues = {
  from_wallet_id: number
  to_wallet_id: number
  amount: number
  to_amount?: number
  note?: string
}

export function CashRegisterTransferButton({ onCreated }: Props) {
  const [open, setOpen] = useState(false)
  const [registers, setRegisters] = useState<CashRegisterDto[]>([])
  const [requesterId, setRequesterId] = useState<number | null>(null)
  const [loadingRegisters, setLoadingRegisters] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [form] = Form.useForm<FormValues>()
  const fromWalletId = Form.useWatch('from_wallet_id', form)
  const toWalletId = Form.useWatch('to_wallet_id', form)

  const openModal = async () => {
    setError(null)
    setOpen(true)
    setLoadingRegisters(true)
    try {
      const [rows, access] = await Promise.all([getCashRegisters(), getSettingsAccess()])
      setRegisters(rows.filter((r) => r.is_active))
      setRequesterId(typeof access.user_id === 'number' ? access.user_id : null)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Не удалось загрузить список касс')
    } finally {
      setLoadingRegisters(false)
    }
  }

  const handleClose = () => {
    setOpen(false)
    form.resetFields()
    setError(null)
  }

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

  const onFinish = async (values: FormValues) => {
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
        toAmount: values.to_amount,
        requesterId,
      })
      message.success('Заявка на перевод создана и отправлена на согласование')
      handleClose()
      onCreated?.()
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

  return (
    <>
      <Button icon={<SwapOutlined />} onClick={() => void openModal()}>
        Перевести между кассами
      </Button>
      <Modal
        title="Перевод между кассами"
        open={open}
        onCancel={handleClose}
        okText="Отправить"
        cancelText="Отмена"
        confirmLoading={submitting}
        destroyOnClose
        onOk={() => form.submit()}
      >
        {error ? <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} /> : null}
        <Form form={form} layout="vertical" onFinish={onFinish} disabled={loadingRegisters}>
          <Form.Item
            name="from_wallet_id"
            label="Из кассы"
            rules={[{ required: true, message: 'Выберите кассу-источник' }]}
          >
            <Select placeholder="Касса-источник" options={fromOptions} />
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
            <Select placeholder="Касса-назначение" options={toOptions} />
          </Form.Item>
          <Form.Item
            name="amount"
            label="Сумма"
            rules={[{ required: true, message: 'Укажите сумму' }]}
          >
            <InputNumber min={0.01} style={{ width: '100%' }} />
          </Form.Item>
          {currencyMismatch && toRegister ? (
            <Form.Item
              name="to_amount"
              label={`Сумма зачисления (${toRegister.currency})`}
              rules={[{ required: true, message: 'Укажите сумму зачисления' }]}
            >
              <InputNumber min={0.01} style={{ width: '100%' }} />
            </Form.Item>
          ) : null}
          <Form.Item name="note" label="Примечание">
            <Input.TextArea rows={2} />
          </Form.Item>
          {fromRegister && toRegister ? (
            <Typography.Text type="secondary">
              {cashRegisterLabel(fromRegister)} ({fromRegister.currency}) → {cashRegisterLabel(toRegister)} (
              {toRegister.currency})
            </Typography.Text>
          ) : null}
        </Form>
      </Modal>
    </>
  )
}
