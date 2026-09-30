import { apiFetch, parseErrorBody } from './api'

export type CashWithdrawalRuleDto = {
  payment_type: string
  payment_purpose: string
  wallet_id: number | null
}

export type CashWithdrawalConfigDto = {
  is_active: boolean
  card_telegram_chat_id: number | null
  alert_telegram_chat_id: number | null
  alert_after_days: number
  alert_repeat_every_days: number
  alert_hour: number
  confirmer_user_ids: number[]
  alert_recipient_user_ids: number[]
  rules: CashWithdrawalRuleDto[]
}

export type CashWithdrawalConfigOptions = {
  users: Array<{ id: number; label: string; has_telegram: boolean }>
  telegram_chats: Array<{ id: number; name: string }>
  wallets: Array<{ id: number; label: string; currency: string }>
  payment_purposes: Array<{ payment_type: string; purposes: string[] }>
}

export type CashWithdrawalConfigResponse = CashWithdrawalConfigDto & { options: CashWithdrawalConfigOptions }

export class CashWithdrawalConfigUnavailableError extends Error {}

const URL = '/api/cash-withdrawals/config/'

async function readConfig(res: Response): Promise<CashWithdrawalConfigResponse> {
  if (res.status === 403 || res.status === 404) {
    throw new CashWithdrawalConfigUnavailableError('Настройка недоступна')
  }
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as CashWithdrawalConfigResponse | null
  if (!json) throw new Error('Пустой ответ от сервера')
  return json
}

export async function getCashWithdrawalConfig(): Promise<CashWithdrawalConfigResponse> {
  return readConfig(await apiFetch(URL))
}

export async function saveCashWithdrawalConfig(payload: CashWithdrawalConfigDto): Promise<CashWithdrawalConfigResponse> {
  return readConfig(
    await apiFetch(URL, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  )
}
