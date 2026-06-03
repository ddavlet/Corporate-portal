import { useEffect, useState } from 'react'
import { Alert, Button, DatePicker, Form, Input, InputNumber, Select, Skeleton, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import { ArrowLeftOutlined } from '@ant-design/icons'

import dayjs from 'dayjs'
import {
  DEFAULT_INVESTMENT_FORM_CONFIG,
  getInvestmentFormConfig,
  getInvestCompanies,
  createInvestReturn,
  type InvestCompanyRow,
} from '../../lib/api'
import { RETURN_CURRENCY_OPTIONS } from '../investments/utils'
import { isAllowedBillingMonth } from '../../lib/billingMonth'
import { monthStartTashkent, nowTashkent } from '../../lib/tashkentTime'
import { useTgMainButton } from './useTgMainButton'

const RECIPIENT_OPTIONS = [
  { value: 'инвестор', label: 'Инвестор' },
  { value: 'партнер', label: 'Партнер' },
]

export function TgInvestmentsReturnCreatePage() {
  const navigate = useNavigate()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [companies, setCompanies] = useState<InvestCompanyRow[]>([])
  const [usesCompanies, setUsesCompanies] = useState(false)
  const [returnTypeOptions, setReturnTypeOptions] = useState<{ value: string; label: string }[]>([])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const cfg = await getInvestmentFormConfig().catch(() => DEFAULT_INVESTMENT_FORM_CONFIG)
        if (cancelled) return
        setUsesCompanies(cfg.uses_companies)
        const allowed = new Set(cfg.allowed_return_types)
        const opts = cfg.return_type_choices.filter((c) => allowed.has(c.value))
        setReturnTypeOptions(opts)
        const defaultType = opts[0]?.value ?? 'дивиденды'
        const bm = monthStartTashkent(nowTashkent())
        form.setFieldsValue({
          date: dayjs(),
          billing_date: bm,
          currency: 'USD',
          type: defaultType,
          recipient: 'инвестор',
        })
        if (cfg.uses_companies) {
          const rows = await getInvestCompanies()
          if (!cancelled) setCompanies(rows)
        }
      } catch {
        // non-fatal
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [form])

  async function handleSubmit() {
    let values: Record<string, unknown>
    try {
      values = await form.validateFields()
    } catch {
      return
    }
    const billingDayjs = values.billing_date as dayjs.Dayjs
    if (!billingDayjs || !isAllowedBillingMonth(billingDayjs)) {
      setError('Выберите допустимый месяц начисления')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      await createInvestReturn({
        company: usesCompanies ? (values.company as number | null) ?? null : null,
        date: dayjs(values.date as dayjs.ConfigType).format('YYYY-MM-DD'),
        billing_date: monthStartTashkent(billingDayjs).format('YYYY-MM-DD'),
        sum: String(values.sum),
        currency: values.currency as string,
        type: values.type as string,
        recipient: values.recipient as string,
        comment: (values.comment as string | undefined) ?? '',
      })
      navigate('/tg/investments/returns', { replace: true })
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Ошибка создания')
    } finally {
      setSubmitting(false)
    }
  }

  useTgMainButton({
    text: 'Создать выплату',
    onClick: () => void handleSubmit(),
    loading: submitting,
    disabled: loading,
  })

  function disabledBillingMonth(current: dayjs.Dayjs): boolean {
    if (!current) return false
    return !isAllowedBillingMonth(current)
  }

  return (
    <div className="tg-investments-page" style={{ paddingBottom: 88 }}>
      <Button
        icon={<ArrowLeftOutlined />}
        size="large"
        onClick={() => navigate('/tg/investments/returns')}
        style={{ marginBottom: 12, borderRadius: 12 }}
      >
        Назад
      </Button>

      <Typography.Title level={4} style={{ margin: '0 0 20px', fontWeight: 700 }}>
        Новая выплата инвестиции
      </Typography.Title>

      {loading ? (
        <Skeleton active paragraph={{ rows: 6 }} />
      ) : (
        <Form form={form} layout="vertical">
          {usesCompanies ? (
            <Form.Item label="Компания" name="company">
              <Select
                allowClear
                size="large"
                placeholder="Без компании"
                options={companies.map((c) => ({ value: c.id, label: c.name }))}
              />
            </Form.Item>
          ) : null}

          <Form.Item
            label="Дата"
            name="date"
            rules={[{ required: true, message: 'Укажите дату' }]}
          >
            <DatePicker
              size="large"
              style={{ width: '100%' }}
              format="DD.MM.YYYY"
            />
          </Form.Item>

          <Form.Item
            label="Месяц начисления"
            name="billing_date"
            rules={[{ required: true, message: 'Укажите месяц начисления' }]}
          >
            <DatePicker
              picker="month"
              size="large"
              style={{ width: '100%' }}
              format="MM.YYYY"
              disabledDate={disabledBillingMonth}
            />
          </Form.Item>

          <Form.Item
            label="Сумма"
            name="sum"
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
            initialValue="USD"
            rules={[{ required: true }]}
          >
            <Select size="large" options={RETURN_CURRENCY_OPTIONS} />
          </Form.Item>

          <Form.Item
            label="Тип выплаты"
            name="type"
            rules={[{ required: true, message: 'Укажите тип выплаты' }]}
          >
            <Select size="large" options={returnTypeOptions} />
          </Form.Item>

          <Form.Item
            label="Получатель"
            name="recipient"
            rules={[{ required: true, message: 'Укажите получателя' }]}
          >
            <Select size="large" options={RECIPIENT_OPTIONS} />
          </Form.Item>

          <Form.Item label="Комментарий" name="comment">
            <Input.TextArea rows={3} maxLength={1000} size="large" />
          </Form.Item>
        </Form>
      )}

      {error ? (
        <Alert type="error" showIcon message={error} style={{ marginBottom: 12, borderRadius: 12 }} />
      ) : null}
    </div>
  )
}
