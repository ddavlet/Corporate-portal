import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, DatePicker, Input, InputNumber, Segmented, Select, Typography, theme } from 'antd'
import { CloseOutlined } from '@ant-design/icons'

import { DEFAULT_INVESTMENT_FORM_CONFIG, getInvestmentFormConfig } from '../../lib/api'
import { isAllowedBillingMonth } from '../../lib/billingMonth'
import { MobileStateWidget } from '../MobileStateWidget'
import { MobileActionsTheme } from '../requests/mobileActionsTheme'
import { Field } from '../requests/MobileFormFieldWidget'
import {
  INVEST_RETURN_RECIPIENT_OPTIONS,
  investReturnDefaults,
  returnTypeOptionsFromConfig,
  useInvestReturnCreateForm,
  validateInvestReturnValues,
  type InvestReturnField,
  type InvestReturnFieldErrors,
  type InvestReturnFormValues,
  type InvestReturnTypeOption,
} from './useInvestReturnCreateForm'
import { InvestmentsAccessGateWidget } from './InvestmentsAccessGateWidget'
import { closeToInvestments } from './investmentsMobileNav'
import { precisionFor, RETURN_CURRENCY_OPTIONS } from './utils'

/**
 * `/investments/returns/new` on a phone: the desktop «Создать выплату» (InvestReturn on approval) as a full-screen
 * form. Defaults, rules and payload are the desktop's (useInvestReturnCreateForm); errors are shown under the fields,
 * the server's error as a toast with the typed values kept. After the payout is created the form is left the way
 * «Закрыть» leaves it (closeToInvestments), so `/investments` does not land in the history twice. Without the
 * «investments» module (a direct link) — «Раздел недоступен», and the form config is not requested.
 */
export function InvestReturnCreateMobilePage() {
  return (
    <InvestmentsAccessGateWidget title="Новая выплата" testId="invest-return-create-mobile">
      <InvestReturnCreateForm />
    </InvestmentsAccessGateWidget>
  )
}

function InvestReturnCreateForm() {
  const { token } = theme.useToken()
  const navigate = useNavigate()
  const [typeOptions, setTypeOptions] = useState<InvestReturnTypeOption[] | null>(null)
  const [values, setValues] = useState<InvestReturnFormValues | null>(null)
  const [errors, setErrors] = useState<InvestReturnFieldErrors>({})
  const bodyRef = useRef<HTMLDivElement>(null)
  const createForm = useInvestReturnCreateForm({ onCreated: () => undefined })

  useEffect(() => {
    let cancelled = false
    getInvestmentFormConfig()
      .catch(() => DEFAULT_INVESTMENT_FORM_CONFIG)
      .then((cfg) => {
        if (cancelled) return
        const options = returnTypeOptionsFromConfig(cfg)
        setTypeOptions(options)
        setValues(investReturnDefaults(options))
      })
    return () => {
      cancelled = true
    }
  }, [])

  const close = () => closeToInvestments(navigate)

  const update = <K extends keyof InvestReturnFormValues>(key: K, value: InvestReturnFormValues[K]) => {
    setValues((prev) => (prev ? { ...prev, [key]: value } : prev))
    if (key in errors) {
      setErrors((prev) => {
        const next = { ...prev }
        delete next[key as InvestReturnField]
        return next
      })
    }
  }

  // A refused submit: bring the first field with an error into view (it renders on the next frame).
  const scrollToFirstError = () => {
    requestAnimationFrame(() => {
      bodyRef.current?.querySelector('[role="alert"]')?.scrollIntoView?.({ block: 'center', behavior: 'smooth' })
    })
  }

  const submit = async () => {
    if (!values || createForm.submitting) return
    const found = validateInvestReturnValues(values)
    if (Object.keys(found).length > 0) {
      setErrors(found)
      scrollToFirstError()
      return
    }
    setErrors({})
    const result = await createForm.submit(values)
    if (result === 'created') close()
    else if (result === 'invalid_month') {
      // The month stopped being allowed between the check and the send (the date changed): say so at the field.
      setErrors({ billing_date: 'Выберите допустимый месяц начисления' })
      scrollToFirstError()
    }
  }

  const errorProps = (field: InvestReturnField, id: string) =>
    errors[field]
      ? { status: 'error' as const, 'aria-invalid': true, 'aria-describedby': `${id}-error` }
      : {}

  let content
  if (!values || !typeOptions) {
    content = <MobileStateWidget state="loading" rows={2} />
  } else {
    content = (
      <>
        <Field label="Месяц начисления" htmlFor="return-billing-month" error={errors.billing_date} errorId="return-billing-month-error">
          <DatePicker
            id="return-billing-month"
            picker="month"
            format="MM.YYYY"
            style={{ width: '100%' }}
            inputReadOnly
            allowClear={false}
            value={values.billing_date}
            onChange={(v) => update('billing_date', v ? v.startOf('month') : null)}
            disabledDate={(current) => !current || !isAllowedBillingMonth(current)}
            {...errorProps('billing_date', 'return-billing-month')}
          />
          <Typography.Text style={{ display: 'block', marginTop: 4, color: token.colorTextSecondary }}>
            Доступны только месяцы, ещё не закрытые начислениями.
          </Typography.Text>
        </Field>
        <Field label="Дата" htmlFor="return-date" error={errors.date} errorId="return-date-error">
          <DatePicker
            id="return-date"
            format="DD.MM.YYYY"
            style={{ width: '100%' }}
            inputReadOnly
            value={values.date}
            onChange={(v) => update('date', v ?? null)}
            {...errorProps('date', 'return-date')}
          />
        </Field>
        <Field
          label={values.currency === 'UZS' ? 'Сумма (UZS)' : 'Сумма (USD)'}
          htmlFor="return-sum"
          error={errors.sum}
          errorId="return-sum-error"
        >
          <InputNumber
            id="return-sum"
            style={{ width: '100%' }}
            min={0}
            precision={precisionFor(values.currency)}
            inputMode="decimal"
            value={values.sum ?? undefined}
            onChange={(v) => update('sum', typeof v === 'number' ? v : null)}
            {...errorProps('sum', 'return-sum')}
          />
        </Field>
        <Field label="Валюта" labelId="return-currency-label" error={errors.currency} errorId="return-currency-error">
          <Segmented
            block
            aria-labelledby="return-currency-label"
            value={values.currency}
            onChange={(v) => update('currency', String(v))}
            options={RETURN_CURRENCY_OPTIONS}
          />
        </Field>
        <Field label="Тип" htmlFor="return-type" error={errors.type} errorId="return-type-error">
          <Select
            id="return-type"
            style={{ width: '100%' }}
            value={values.type || undefined}
            onChange={(v: string) => update('type', v)}
            options={typeOptions.length > 0 ? typeOptions : [{ value: values.type, label: values.type }]}
            {...errorProps('type', 'return-type')}
          />
        </Field>
        <Field label="Получатель" labelId="return-recipient-label" error={errors.recipient} errorId="return-recipient-error">
          <Segmented
            block
            aria-labelledby="return-recipient-label"
            value={values.recipient}
            onChange={(v) => update('recipient', String(v))}
            options={INVEST_RETURN_RECIPIENT_OPTIONS}
          />
        </Field>
        <Field label="Комментарий" htmlFor="return-comment">
          <Input.TextArea
            id="return-comment"
            autoSize={{ minRows: 3, maxRows: 8 }}
            maxLength={500}
            value={values.comment ?? ''}
            onChange={(e) => update('comment', e.target.value)}
          />
        </Field>
      </>
    )
  }

  return (
    <div className="m-fullscreen m-root" data-testid="invest-return-create-mobile" style={{ background: token.colorBgLayout }}>
      <header
        className="m-header"
        style={{ position: 'static', background: token.colorBgContainer, borderBottom: `1px solid ${token.colorBorderSecondary}` }}
      >
        <Button type="text" className="m-header__button" icon={<CloseOutlined />} aria-label="Закрыть" onClick={close} />
        <h1 className="m-header__title m-ellipsis">Новая выплата</h1>
      </header>

      <div ref={bodyRef} className="m-fullscreen__body">
        <div style={{ display: 'grid', gap: 16, padding: 16, minWidth: 0 }}>{content}</div>
      </div>

      <MobileActionsTheme>
        <div
          className="m-bottom-bar"
          style={{ position: 'static', background: token.colorBgContainer, borderTop: `1px solid ${token.colorBorderSecondary}` }}
        >
          <Button
            type="primary"
            block
            style={{ height: 44 }}
            loading={createForm.submitting}
            disabled={!values || createForm.submitting}
            onClick={() => void submit()}
          >
            Создать выплату
          </Button>
        </div>
      </MobileActionsTheme>
    </div>
  )
}
