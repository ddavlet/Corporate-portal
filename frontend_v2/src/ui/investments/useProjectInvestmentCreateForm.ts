import { useCallback, useRef, useState } from 'react'
import { message } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'

import { createProjectInvestment, type CreateProjectInvestmentPayload } from '../../lib/api'
import { FUNDING_METHOD_LABELS, type FundingMethod } from './fundingPool'

/** Values of the phone «Подать заявку на вложение» form; the fields of the desktop modal in InvestmentsTab. */
export type ProjectInvestmentFormValues = {
  date: Dayjs | null
  amount: number | null
  currency: string
  funding_method: FundingMethod | null
  comment: string
}

export type ProjectInvestmentField = 'date' | 'amount' | 'currency' | 'funding_method'

export type ProjectInvestmentFieldErrors = Partial<Record<ProjectInvestmentField, string>>

export type ProjectInvestmentSubmitResult = 'created' | 'busy' | 'failed'

export const PROJECT_INVESTMENT_FUNDING_METHOD_OPTIONS: { value: FundingMethod; label: string }[] = [
  { value: 'cash', label: FUNDING_METHOD_LABELS.cash },
  { value: 'bank_transfer', label: FUNDING_METHOD_LABELS.bank_transfer },
]

/** Defaults of the desktop modal: today, USD, no sum and no funding method. */
export function projectInvestmentDefaults(): ProjectInvestmentFormValues {
  return { date: dayjs(), amount: null, currency: 'USD', funding_method: null, comment: '' }
}

/** Errors of the required fields (the desktop modal's rules); empty when the form can be sent. */
export function validateProjectInvestmentValues(v: ProjectInvestmentFormValues): ProjectInvestmentFieldErrors {
  const errors: ProjectInvestmentFieldErrors = {}
  if (!v.date) errors.date = 'Укажите дату'
  if (v.amount == null || !Number.isFinite(v.amount)) errors.amount = 'Укажите сумму'
  if (!v.currency) errors.currency = 'Выберите валюту'
  if (!v.funding_method) errors.funding_method = 'Укажите способ внесения'
  return errors
}

function toPayload(v: ProjectInvestmentFormValues): CreateProjectInvestmentPayload {
  if (!v.date || v.amount == null || !v.funding_method) throw new Error('Заполните обязательные поля')
  return {
    date: v.date.format('YYYY-MM-DD'),
    amount: String(v.amount),
    currency: v.currency,
    comment: v.comment ?? '',
    funding_method: v.funding_method,
  }
}

/**
 * Sending of the phone «Подать заявку на вложение» form: the desktop payload and messages. The page validates the
 * fields itself; a second call while one is in flight sends nothing (`'busy'`). The server's refusal is shown as a
 * toast and returns `'failed'`, so the page keeps the typed values.
 */
export function useProjectInvestmentCreateForm() {
  const [submitting, setSubmitting] = useState(false)
  const submittingRef = useRef(false)

  const submit = useCallback(async (values: ProjectInvestmentFormValues): Promise<ProjectInvestmentSubmitResult> => {
    if (submittingRef.current) return 'busy'
    submittingRef.current = true
    setSubmitting(true)
    try {
      await createProjectInvestment(toPayload(values))
      message.success('Заявка на вложение создана')
      return 'created'
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Не удалось создать заявку на вложение')
      return 'failed'
    } finally {
      submittingRef.current = false
      setSubmitting(false)
    }
  }, [])

  return { submitting, submit }
}
