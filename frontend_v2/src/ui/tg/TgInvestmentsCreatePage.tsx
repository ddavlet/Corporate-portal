import { useEffect, useState } from 'react'
import { Alert, Button, DatePicker, Form, Input, InputNumber, Select, Skeleton, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import { ArrowLeftOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  DEFAULT_INVESTMENT_FORM_CONFIG,
  getInvestmentFormConfig,
  getInvestCompanies,
  createProjectInvestment,
  type InvestCompanyRow,
} from '../../lib/api'
import { CURRENCY_OPTIONS } from '../investments/utils'

export function TgInvestmentsCreatePage() {
  const navigate = useNavigate()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [companies, setCompanies] = useState<InvestCompanyRow[]>([])
  const [usesCompanies, setUsesCompanies] = useState(false)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const cfg = await getInvestmentFormConfig().catch(() => DEFAULT_INVESTMENT_FORM_CONFIG)
        if (cancelled) return
        setUsesCompanies(cfg.uses_companies)
        if (cfg.uses_companies) {
          const rows = await getInvestCompanies()
          if (!cancelled) setCompanies(rows)
        }
      } catch {
        // non-fatal — form still usable without companies
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

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
        company: usesCompanies ? (values.company as number | null) ?? null : null,
        date: dayjs(values.date as dayjs.ConfigType).format('YYYY-MM-DD'),
        amount: String(values.amount),
        currency: values.currency as string,
        comment: (values.comment as string | undefined) ?? '',
      })
      navigate('/tg/investments/projects', { replace: true })
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Ошибка создания')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="tg-investments-page" style={{ paddingBottom: 88 }}>
      <Button
        icon={<ArrowLeftOutlined />}
        size="large"
        onClick={() => navigate('/tg/investments/projects')}
        style={{ marginBottom: 12, borderRadius: 12 }}
      >
        Назад
      </Button>

      <Typography.Title level={4} style={{ margin: '0 0 20px', fontWeight: 700 }}>
        Новая заявка на вложение
      </Typography.Title>

      {loading ? (
        <Skeleton active paragraph={{ rows: 5 }} />
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

          <Form.Item label="Комментарий" name="comment">
            <Input.TextArea rows={3} maxLength={1000} size="large" />
          </Form.Item>
        </Form>
      )}

      {error ? (
        <Alert type="error" showIcon message={error} style={{ marginBottom: 12, borderRadius: 12 }} />
      ) : null}

      <div className="tg-sticky-action-bar">
        <Button
          type="primary"
          size="large"
          block
          loading={submitting}
          disabled={loading}
          onClick={handleSubmit}
        >
          Создать заявку
        </Button>
      </div>
    </div>
  )
}
