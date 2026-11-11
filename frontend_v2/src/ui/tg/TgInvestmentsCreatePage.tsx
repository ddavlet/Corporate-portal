import { useEffect, useState } from 'react'
import { Alert, DatePicker, Form, Input, InputNumber, Select, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import { createProjectInvestment } from '../../lib/api'
import { useInvestmentFundingMode } from '../../lib/useInvestmentFundingMode'
import { CURRENCY_OPTIONS } from '../investments/utils'
import { FUNDING_METHOD_LABELS, type FundingMethod } from '../investments/fundingPool'
import { useTgMainButton } from './useTgMainButton'

export function TgInvestmentsCreatePage() {
  const navigate = useNavigate()
  const [form] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fundingMode = useInvestmentFundingMode()

  // В инвестиционном режиме ручная подача запрещена (backend отклонит) — ведём на сбор по заявкам.
  useEffect(() => {
    if (fundingMode) navigate('/tg/investments/projects/collect', { replace: true })
  }, [fundingMode, navigate])

  async function handleSubmit() {
    let values: Record<string, unknown>
    try {
      values = await form.validateFields()
    } catch {
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      await createProjectInvestment({
        date: dayjs(values.date as dayjs.ConfigType).format('YYYY-MM-DD'),
        amount: String(values.amount),
        currency: values.currency as string,
        comment: (values.comment as string | undefined) ?? '',
        funding_method: values.funding_method as FundingMethod,
      })
      navigate('/tg/investments/projects', { replace: true })
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Ошибка создания')
    } finally {
      setSubmitting(false)
    }
  }

  useTgMainButton({
    text: 'Создать заявку',
    onClick: () => void handleSubmit(),
    loading: submitting,
  })

  return (
    <div className="tg-investments-page" style={{ paddingBottom: 88 }}>
      <Typography.Title level={4} style={{ margin: '0 0 20px', fontWeight: 700 }}>
        Новая заявка на вложение
      </Typography.Title>

      <Form form={form} layout="vertical">
        <Form.Item
          label="Дата"
          name="date"
          rules={[{ required: true, message: 'Укажите дату' }]}
        >
          <DatePicker
            size="large"
            style={{ width: '100%' }}
            format="DD.MM.YYYY"
            defaultPickerValue={dayjs()}
          />
        </Form.Item>

        <Form.Item
          label="Сумма"
          name="amount"
          rules={[{ required: true, message: 'Укажите сумму' }]}
        >
          <InputNumber
            size="large"
            min={0}
            style={{ width: '100%' }}
            placeholder="0"
          />
        </Form.Item>

        <Form.Item
          label="Валюта"
          name="currency"
          initialValue="UZS"
          rules={[{ required: true }]}
        >
          <Select size="large" options={CURRENCY_OPTIONS} />
        </Form.Item>

        <Form.Item
          label="Способ внесения"
          name="funding_method"
          rules={[{ required: true, message: 'Укажите способ внесения' }]}
        >
          <Select
            size="large"
            placeholder="Выберите способ"
            getPopupContainer={() => document.body}
            options={[
              { value: 'cash', label: FUNDING_METHOD_LABELS.cash },
              { value: 'bank_transfer', label: FUNDING_METHOD_LABELS.bank_transfer },
            ]}
          />
        </Form.Item>

        <Form.Item label="Комментарий" name="comment">
          <Input.TextArea rows={3} maxLength={1000} size="large" />
        </Form.Item>
      </Form>

      {error ? (
        <Alert type="error" showIcon message={error} style={{ marginBottom: 12, borderRadius: 12 }} />
      ) : null}
    </div>
  )
}
