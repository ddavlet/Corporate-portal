import { useState } from 'react'
import { Alert, Button, Form, Input, InputNumber, Modal, Select, Typography, message } from 'antd'
import { SwapOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { createPortalRequest, getCashRegisters, submitRequestForApproval, type CashRegisterDto } from '../lib/api'

export const CASH_REGISTER_TRANSFER_PAYMENT_TYPE = 'Наличные'
export const CASH_REGISTER_TRANSFER_PAYMENT_PURPOSE = 'Перевод между кассами'

type Props = {
  /** Перезагрузка списка операций после успешной отправки заявки. */
  onCreated?: () => void
}

type FormValues = {
  from_wallet_id: number
  to_wallet_id: number
  amount: number
  note?: string
}

function registerLabel(r: CashRegisterDto): string {
  return (r.name || '').trim() || r.currency
}

export function CashRegisterTransferButton({ onCreated }: Props) {
  const [open, setOpen] = useState(false)
  const [registers, setRegisters] = useState<CashRegisterDto[]>([])
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
      const rows = await getCashRegisters()
      setRegisters(rows.filter((r) => r.is_active))
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
    .map((r) => ({ value: r.id, label: registerLabel(r) }))
  const toOptions = registers
    .filter((r) => r.id !== fromWalletId)
    .map((r) => ({ value: r.id, label: registerLabel(r) }))

  const onFinish = async (values: FormValues) => {
    const fromReg = registers.find((r) => r.id === values.from_wallet_id)
    const toReg = registers.find((r) => r.id === values.to_wallet_id)
    if (!fromReg || !toReg) return

    const fromLabel = registerLabel(fromReg)
    const toLabel = registerLabel(toReg)
    const descriptionLines = [
      'Перевод ДС между кассами.',
      `Из кассы: ${fromLabel} (${fromReg.currency})`,
      `В кассу: ${toLabel} (${toReg.currency})`,
    ]
    const note = (values.note || '').trim()
    if (note) descriptionLines.push(`Примечание: ${note}`)

    setSubmitting(true)
    setError(null)
    try {
      const created = await createPortalRequest({
        title: `Перевод: ${fromLabel} → ${toLabel}`,
        description: descriptionLines.join('\n'),
        amount: values.amount,
        currency: fromReg.currency,
        payment_type: CASH_REGISTER_TRANSFER_PAYMENT_TYPE,
        payment_purpose: CASH_REGISTER_TRANSFER_PAYMENT_PURPOSE,
        urgency: 'Обычно',
        billing_date: dayjs().format('YYYY-MM-DD'),
        status: 'DRAFT',
        amortization_months: 1,
      })
      try {
        await submitRequestForApproval(created.id)
        message.success('Заявка на перевод создана и отправлена на согласование')
        handleClose()
        onCreated?.()
      } catch (submitErr: unknown) {
        setError(
          `Заявка №${created.id} создана, но не отправлена на согласование: ` +
            (submitErr instanceof Error ? submitErr.message : 'ошибка'),
        )
      }
    } catch (createErr: unknown) {
      setError(createErr instanceof Error ? createErr.message : 'Не удалось создать заявку')
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
          {currencyMismatch ? (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 16 }}
              message="Кассы в разных валютах — уточните сумму зачисления в примечании."
            />
          ) : null}
          <Form.Item
            name="amount"
            label="Сумма"
            rules={[{ required: true, message: 'Укажите сумму' }]}
          >
            <InputNumber min={0.01} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="note" label="Примечание">
            <Input.TextArea rows={2} />
          </Form.Item>
          {fromRegister && toRegister ? (
            <Typography.Text type="secondary">
              {registerLabel(fromRegister)} ({fromRegister.currency}) → {registerLabel(toRegister)} (
              {toRegister.currency})
            </Typography.Text>
          ) : null}
        </Form>
      </Modal>
    </>
  )
}
