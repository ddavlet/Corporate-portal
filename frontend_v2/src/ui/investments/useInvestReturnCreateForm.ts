import { useCallback, useRef, useState } from 'react'
import { message } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'

import { createInvestReturn, type CreateInvestReturnPayload, type InvestmentFormConfigResponse } from '../../lib/api'
import { clampToAllowedBillingMonth, isAllowedBillingMonth } from '../../lib/billingMonth'
import { monthStartTashkent } from '../../lib/tashkentTime'

/** Values of the «Создать выплату» form (InvestReturn on approval): the desktop modal and the phone page. */
export type InvestReturnFormValues = {
  date: Dayjs | null
  billing_date: Dayjs | null
  sum: number | null
  currency: string
  type: string
  recipient: string
  comment?: string
}

export type InvestReturnField = 'billing_date' | 'date' | 'sum' | 'currency' | 'type' | 'recipient'

export type InvestReturnFieldErrors = Partial<Record<InvestReturnField, string>>

export type InvestReturnTypeOption = { value: string; label: string }

export type InvestReturnSubmitResult = 'created' | 'invalid_month' | 'busy' | 'failed'

export const INVEST_RETURN_RECIPIENT_OPTIONS = [
  { value: 'инвестор', label: 'Инвестор' },
  { value: 'партнер', label: 'Партнер' },
]

/** Fallback type when the tenant allows none (the same as the desktop form always had). */
const FALLBACK_RETURN_TYPE = 'дивиденды'

/** Types of payouts the tenant allows, in the order of the choices. */
export function returnTypeOptionsFromConfig(cfg: InvestmentFormConfigResponse): InvestReturnTypeOption[] {
  const allowed = new Set(cfg.allowed_return_types)
  return cfg.return_type_choices.filter((c) => allowed.has(c.value))
}

/** Defaults of a new payout: today, the current accrual month (or the nearest allowed), USD, first type, investor. */
export function investReturnDefaults(returnTypeOptions: InvestReturnTypeOption[]): InvestReturnFormValues {
  return {
    date: dayjs(),
    billing_date: clampToAllowedBillingMonth(monthStartTashkent(dayjs())),
    sum: null,
    currency: 'USD',
    type: returnTypeOptions[0]?.value ?? FALLBACK_RETURN_TYPE,
    recipient: 'инвестор',
    comment: '',
  }
}

/** Errors of the required fields and of an accrual month that is no longer allowed; empty when the form can be sent. */
export function validateInvestReturnValues(v: InvestReturnFormValues): InvestReturnFieldErrors {
  const errors: InvestReturnFieldErrors = {}
  if (!v.billing_date) errors.billing_date = 'Укажите месяц начисления'
  else if (!isAllowedBillingMonth(v.billing_date)) errors.billing_date = 'Выберите допустимый месяц начисления'
  if (!v.date) errors.date = 'Укажите дату'
  if (v.sum == null || !Number.isFinite(v.sum)) errors.sum = 'Укажите сумму'
  if (!v.currency) errors.currency = 'Выберите валюту'
  if (!v.type) errors.type = 'Выберите тип'
  if (!v.recipient) errors.recipient = 'Выберите получателя'
  return errors
}

function toPayload(v: InvestReturnFormValues): CreateInvestReturnPayload {
  if (!v.date || !v.billing_date || v.sum == null) throw new Error('Заполните обязательные поля')
  return {
    date: v.date.format('YYYY-MM-DD'),
    billing_date: v.billing_date.startOf('month').format('YYYY-MM-DD'),
    sum: String(v.sum),
    currency: v.currency,
    type: v.type,
    recipient: v.recipient,
    comment: v.comment ?? '',
  }
}

export type UseInvestReturnCreateFormOptions = {
  /** After the payout is created and the success message is shown; its failure is reported like a failed create. */
  onCreated: () => Promise<void> | void
}

/**
 * Sending of the «Создать выплату» form without its markup: the desktop modal (antd Form) and the phone page (own
 * state) validate the fields themselves and call `submit`. A second call while one is in flight sends nothing
 * (`'busy'`). A month that is not allowed any more returns `'invalid_month'` and shows nothing: the caller says so
 * in its own place (a toast on the desktop, under the field on the phone).
 */
export function useInvestReturnCreateForm({ onCreated }: UseInvestReturnCreateFormOptions) {
  const [submitting, setSubmitting] = useState(false)
  const submittingRef = useRef(false)
  const onCreatedRef = useRef(onCreated)
  onCreatedRef.current = onCreated

  const submit = useCallback(async (values: InvestReturnFormValues): Promise<InvestReturnSubmitResult> => {
    if (submittingRef.current) return 'busy'
    if (!values.billing_date || !isAllowedBillingMonth(values.billing_date)) return 'invalid_month'
    submittingRef.current = true
    setSubmitting(true)
    try {
      await createInvestReturn(toPayload(values))
      message.success('Выплата создана и отправлена на согласование')
      await onCreatedRef.current()
      return 'created'
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Не удалось создать выплату')
      return 'failed'
    } finally {
      submittingRef.current = false
      setSubmitting(false)
    }
  }, [])

  return { submitting, submit }
}
