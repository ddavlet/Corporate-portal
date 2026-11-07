import { apiFetch, parseErrorBody } from './api'

export type DividendReturnType = 'дивиденды' | 'проценты' | 'доля_прибыли' | 'тело_инвестиций'
export type DividendRecipient = 'инвестор' | 'партнер'

export type DividendPayoutRuleDto = {
  payment_purpose: string
  return_type: DividendReturnType | string
  recipient: DividendRecipient | string
  is_active: boolean
}

export type DividendPayoutRule = DividendPayoutRuleDto & { id: number }

export type DividendPayoutOption = { value: string; label: string }

export type DividendPayoutOptions = {
  return_types: DividendPayoutOption[]
  recipients: DividendPayoutOption[]
  payment_purposes: string[]
}

/**
 * Ошибка HTTP модуля правил дивидендов.
 * status 404 — модуль недоступен/выключен; fieldErrors — ошибки валидации DRF по полям (400).
 */
export class DividendPayoutsApiError extends Error {
  status: number
  fieldErrors: Record<string, string[]>

  constructor(status: number, message: string, fieldErrors: Record<string, string[]> = {}) {
    super(message)
    this.status = status
    this.fieldErrors = fieldErrors
  }
}

const RULES_URL = '/api/dividend-payouts/rules/'
const OPTIONS_URL = '/api/dividend-payouts/options/'

function toFieldErrors(json: unknown): Record<string, string[]> {
  if (!json || typeof json !== 'object' || Array.isArray(json)) return {}
  const out: Record<string, string[]> = {}
  for (const [key, value] of Object.entries(json as Record<string, unknown>)) {
    if (key === 'detail') continue
    if (Array.isArray(value)) out[key] = value.filter((v): v is string => typeof v === 'string')
    else if (typeof value === 'string') out[key] = [value]
  }
  return out
}

async function raise(res: Response): Promise<never> {
  const json = await res
    .clone()
    .json()
    .catch(() => null)
  throw new DividendPayoutsApiError(res.status, await parseErrorBody(res), res.status === 400 ? toFieldErrors(json) : {})
}

async function readJson<T>(res: Response): Promise<T> {
  if (!res.ok) await raise(res)
  const json = (await res.json().catch(() => null)) as T | null
  if (json === null) throw new DividendPayoutsApiError(res.status, 'Пустой ответ от сервера')
  return json
}

// GET-запросы silent: 404 (модуль выключен) страница показывает сама, без глобального тоста.
export async function listDividendPayoutRules(): Promise<DividendPayoutRule[]> {
  return readJson(await apiFetch(RULES_URL, {}, { silent: true }))
}

export async function getDividendPayoutOptions(): Promise<DividendPayoutOptions> {
  return readJson(await apiFetch(OPTIONS_URL, {}, { silent: true }))
}

export async function createDividendPayoutRule(dto: DividendPayoutRuleDto): Promise<DividendPayoutRule> {
  return readJson(
    await apiFetch(RULES_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(dto),
    }),
  )
}

export async function updateDividendPayoutRule(
  id: number,
  patch: Partial<DividendPayoutRuleDto>,
): Promise<DividendPayoutRule> {
  return readJson(
    await apiFetch(`${RULES_URL}${id}/`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    }),
  )
}

export async function deleteDividendPayoutRule(id: number): Promise<void> {
  const res = await apiFetch(`${RULES_URL}${id}/`, { method: 'DELETE' })
  if (!res.ok) await raise(res)
}
