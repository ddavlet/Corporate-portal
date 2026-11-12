import { useRef, useState, type ReactNode, type Ref } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, DatePicker, Input, InputNumber, Segmented, Select, theme } from 'antd'
import { CloseOutlined, MergeCellsOutlined } from '@ant-design/icons'

import { useInvestmentFundingModeStatus } from '../../lib/useInvestmentFundingModeStatus'
import { MobileStateWidget } from '../MobileStateWidget'
import { MobileActionsTheme } from '../requests/mobileActionsTheme'
import { Field } from '../requests/MobileFormFieldWidget'
import type { FundingMethod } from './fundingPool'
import { InvestmentsAccessGateWidget } from './InvestmentsAccessGateWidget'
import { closeToInvestments, INVESTMENT_COLLECT_PATH } from './investmentsMobileNav'
import {
  PROJECT_INVESTMENT_FUNDING_METHOD_OPTIONS,
  projectInvestmentDefaults,
  useProjectInvestmentCreateForm,
  validateProjectInvestmentValues,
  type ProjectInvestmentField,
  type ProjectInvestmentFieldErrors,
  type ProjectInvestmentFormValues,
} from './useProjectInvestmentCreateForm'
import { CURRENCY_OPTIONS, precisionFor } from './utils'

const TITLE = 'Заявка на вложение'
const TEST_ID = 'investment-create-mobile'

/**
 * `/investments/new` on a phone: the desktop «Подать заявку на вложение» modal (InvestmentsTab) as a full-screen
 * form, with its defaults, rules and payload. Errors are shown under the fields, the server's error as a toast with
 * the typed values kept; after the request is created the form is left the way «Закрыть» leaves it
 * (closeToInvestments). In the investment mode investments are collected from requests, so a direct link shows a
 * hint with «Собрать из заявок» instead of the form (the server refuses a manual one anyway). Without the
 * «investments» module — «Раздел недоступен», and nothing is requested.
 */
export function InvestmentCreateMobilePage() {
  return (
    <InvestmentsAccessGateWidget title={TITLE} testId={TEST_ID}>
      <InvestmentCreateScreen />
    </InvestmentsAccessGateWidget>
  )
}

function InvestmentCreateScreen() {
  const navigate = useNavigate()
  const fundingMode = useInvestmentFundingModeStatus()
  const close = () => closeToInvestments(navigate)

  if (fundingMode.loading) {
    return (
      <Screen onClose={close}>
        <div style={{ padding: 16 }}>
          <MobileStateWidget state="loading" rows={2} />
        </div>
      </Screen>
    )
  }

  if (fundingMode.enabled) {
    return (
      <Screen onClose={close}>
        <div style={{ padding: 16 }}>
          <MobileStateWidget
            state="empty"
            title="Вложения собираются из заявок"
            description="В инвестиционном режиме заявку на вложение вручную не подают: её собирают из одобренных заявок."
            action={
              <MobileActionsTheme>
                <Button
                  type="primary"
                  icon={<MergeCellsOutlined />}
                  onClick={() => navigate(INVESTMENT_COLLECT_PATH, { replace: true })}
                >
                  Собрать из заявок
                </Button>
              </MobileActionsTheme>
            }
          />
        </div>
      </Screen>
    )
  }

  return <InvestmentCreateForm onClose={close} />
}

/** The full-screen frame: «Закрыть» and the heading on top, the body, an optional bottom bar. */
function Screen({ onClose, bottom, bodyRef, children }: {
  onClose: () => void
  bottom?: ReactNode
  bodyRef?: Ref<HTMLDivElement>
  children: ReactNode
}) {
  const { token } = theme.useToken()
  return (
    <div className="m-fullscreen m-root" data-testid={TEST_ID} style={{ background: token.colorBgLayout }}>
      <header
        className="m-header"
        style={{ position: 'static', background: token.colorBgContainer, borderBottom: `1px solid ${token.colorBorderSecondary}` }}
      >
        <Button type="text" className="m-header__button" icon={<CloseOutlined />} aria-label="Закрыть" onClick={onClose} />
        <h1 className="m-header__title m-ellipsis">{TITLE}</h1>
      </header>
      <div ref={bodyRef} className="m-fullscreen__body">
        {children}
      </div>
      {bottom}
    </div>
  )
}

function InvestmentCreateForm({ onClose }: { onClose: () => void }) {
  const { token } = theme.useToken()
  const [values, setValues] = useState<ProjectInvestmentFormValues>(projectInvestmentDefaults)
  const [errors, setErrors] = useState<ProjectInvestmentFieldErrors>({})
  const bodyRef = useRef<HTMLDivElement>(null)
  const createForm = useProjectInvestmentCreateForm()

  const clearError = (field: ProjectInvestmentField) => {
    if (!(field in errors)) return
    setErrors((prev) => {
      const next = { ...prev }
      delete next[field]
      return next
    })
  }

  const update = <K extends keyof ProjectInvestmentFormValues>(key: K, value: ProjectInvestmentFormValues[K]) => {
    setValues((prev) => ({ ...prev, [key]: value }))
    if (key !== 'comment') clearError(key as ProjectInvestmentField)
  }

  // As on the desktop: another currency has another precision, so the sum is typed again.
  const changeCurrency = (currency: string) => {
    if (currency === values.currency) return
    setValues((prev) => ({ ...prev, currency, amount: null }))
    clearError('currency')
  }

  // A refused submit: bring the first field with an error into view (it renders on the next frame).
  const scrollToFirstError = () => {
    requestAnimationFrame(() => {
      bodyRef.current?.querySelector('[role="alert"]')?.scrollIntoView?.({ block: 'center', behavior: 'smooth' })
    })
  }

  const submit = async () => {
    if (createForm.submitting) return
    const found = validateProjectInvestmentValues(values)
    if (Object.keys(found).length > 0) {
      setErrors(found)
      scrollToFirstError()
      return
    }
    setErrors({})
    const result = await createForm.submit(values)
    if (result === 'created') onClose()
  }

  const errorProps = (field: ProjectInvestmentField, id: string) =>
    errors[field]
      ? { status: 'error' as const, 'aria-invalid': true, 'aria-describedby': `${id}-error` }
      : {}

  const bottom = (
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
          disabled={createForm.submitting}
          onClick={() => void submit()}
        >
          Отправить
        </Button>
      </div>
    </MobileActionsTheme>
  )

  return (
    <Screen onClose={onClose} bottom={bottom} bodyRef={bodyRef}>
      <div style={{ display: 'grid', gap: 16, padding: 16, minWidth: 0 }}>
        <Field label="Дата" htmlFor="investment-date" error={errors.date} errorId="investment-date-error">
          <DatePicker
            id="investment-date"
            format="DD.MM.YYYY"
            style={{ width: '100%' }}
            inputReadOnly
            value={values.date}
            onChange={(v) => update('date', v ?? null)}
            {...errorProps('date', 'investment-date')}
          />
        </Field>
        <Field
          label={`Сумма (${values.currency})`}
          htmlFor="investment-amount"
          error={errors.amount}
          errorId="investment-amount-error"
        >
          <InputNumber
            id="investment-amount"
            style={{ width: '100%' }}
            min={0}
            precision={precisionFor(values.currency)}
            inputMode="decimal"
            value={values.amount ?? null}
            onChange={(v) => update('amount', typeof v === 'number' ? v : null)}
            {...errorProps('amount', 'investment-amount')}
          />
        </Field>
        <Field label="Валюта" labelId="investment-currency-label" error={errors.currency} errorId="investment-currency-error">
          <Segmented
            block
            aria-labelledby="investment-currency-label"
            value={values.currency}
            onChange={(v) => changeCurrency(String(v))}
            options={CURRENCY_OPTIONS}
          />
        </Field>
        <Field
          label="Способ внесения"
          htmlFor="investment-funding-method"
          error={errors.funding_method}
          errorId="investment-funding-method-error"
        >
          <Select<FundingMethod>
            id="investment-funding-method"
            style={{ width: '100%' }}
            placeholder="Выберите способ"
            value={values.funding_method ?? undefined}
            onChange={(v) => update('funding_method', v)}
            options={PROJECT_INVESTMENT_FUNDING_METHOD_OPTIONS}
            {...errorProps('funding_method', 'investment-funding-method')}
          />
        </Field>
        <Field label="Комментарий" htmlFor="investment-comment">
          <Input.TextArea
            id="investment-comment"
            autoSize={{ minRows: 3, maxRows: 8 }}
            maxLength={1000}
            value={values.comment}
            onChange={(e) => update('comment', e.target.value)}
          />
        </Field>
      </div>
    </Screen>
  )
}
