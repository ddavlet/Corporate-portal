import { apiFetch, parseErrorBody, type PayrollPayoutStateDto } from './api'

/** Card payout (transit 23106) not yet tied to a portal employee. */
export type PayrollCardUnlinkedDto = {
  payout_id: number
  bank_employee_id: number | null
  bank_full_name: string | null
  name_from_purpose: string
  masked_card: string | null
  card_account_masked: string
  amount: string
  paid_on: string
  batch_num: string | null
  batch_date: string | null
  candidate: { id: number; full_name: string } | null
}

/** Employee is known, but there is no accepted accrual for the period yet. */
export type PayrollCardAwaitingDto = {
  payout_id: number
  employee_id: number
  full_name: string
  period_month: string
  amount: string
  paid_on: string
}

/** Card was expected for the employee in an accepted accrual but did not arrive. */
export type PayrollCardMissingDto = {
  document_id: number
  document_label: string
  employee_id: number
  full_name: string
  expected: string
}

/** Cash + card above the accrued sum. */
export type PayrollCardOverpaidDto = {
  document_id: number
  document_label: string
  period_month: string | null
  employee_id: number
  full_name: string
  accrued: string
  cash: string
  card: string
  overpaid: string
}

export type PayrollCardAttentionGroup = 'unlinked' | 'awaiting_document' | 'missing_card' | 'overpaid'

export type PayrollCardAttentionDto = {
  /** false while card accounting is off for the tenant (no start period, legacy mode). */
  enabled: boolean
  /** Sum of all four groups before they are cut to the first 200 rows. */
  count: number
  /** Full size of every group (the lists are cut to the first 200 rows); absent on older backends. */
  counts?: Record<PayrollCardAttentionGroup, number>
  unlinked: PayrollCardUnlinkedDto[]
  awaiting_document: PayrollCardAwaitingDto[]
  missing_card: PayrollCardMissingDto[]
  overpaid: PayrollCardOverpaidDto[]
}

export type BankEmployeeLinkDto = {
  id: number
  bank_employee_id: number
  employee_id: number
  full_name: string
}

export type CardPayoutAssignDto = {
  payout_id: number
  employee_id: number
  document_id: number | null
}

/** HTTP error of the card payouts API; message is the server text (DRF detail or field errors). */
export class PayrollCardApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'PayrollCardApiError'
    this.status = status
  }
}

const BASE = '/api/payroll'

async function readJson<T>(res: Response): Promise<T> {
  if (!res.ok) throw new PayrollCardApiError(res.status, await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as T | null
  if (json === null) throw new PayrollCardApiError(res.status, 'Пустой ответ от сервера')
  return json
}

function jsonInit(method: string, body: unknown): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
}

/**
 * Review state of card payouts. null when the user has no payroll role or the module is off (403/404):
 * the menu counter and the review screen just stay empty. Silent: no global error toast.
 */
export async function getPayrollCardAttention(): Promise<PayrollCardAttentionDto | null> {
  const res = await apiFetch(`${BASE}/card-payouts/attention/`, {}, { silent: true })
  if (res.status === 403 || res.status === 404) return null
  return readJson<PayrollCardAttentionDto>(res)
}

/** All rows of this bank employee in the tenant (past and future) go to the portal employee. */
export async function linkBankEmployee(payload: {
  bank_employee_id: number
  employee_id: number
}): Promise<BankEmployeeLinkDto> {
  return readJson(await apiFetch(`${BASE}/bank-employee-links/`, jsonInit('POST', payload)))
}

/** One-off: only this payout (it has no bank employee id) goes to the employee. */
export async function assignCardPayout(payoutId: number, employeeId: number): Promise<CardPayoutAssignDto> {
  return readJson(
    await apiFetch(`${BASE}/card-payouts/${payoutId}/assign/`, jsonInit('POST', { employee_id: employeeId })),
  )
}

/** Expected card amounts of a draft or accepted accrual; returns the new payout state. */
export async function updateExpectedCard(
  documentId: number,
  items: { employee_id: number; amount: string }[],
): Promise<PayrollPayoutStateDto> {
  return readJson(await apiFetch(`${BASE}/documents/${documentId}/expected-card/`, jsonInit('PUT', { items })))
}
