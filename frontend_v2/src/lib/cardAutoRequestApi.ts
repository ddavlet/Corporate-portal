import { apiFetch, parseErrorBody } from './api'

export type CardAutoRequestConfigDto = {
  is_enabled?: boolean
  payment_purpose?: string
  category?: string
  company_payer?: string
  vendor_ref_id?: number | null
  match_text?: string
}

export type CardAutoRequestConfigResponse = {
  wallet_id: number
  wallet_label: string
  currency: string
  is_enabled: boolean
  payment_purpose: string
  category: string
  company_payer: string
  vendor_ref_id: number | null
  match_text: string
  updated_at: string | null
  options: {
    payment_purposes: Array<{ name: string; category: string }>
    vendors: Array<{ id: number; name: string }>
    default_company_payer: string
  }
}

/** 403 — настройку меняет только администратор; 404 — модуль/кошелёк недоступен. */
export class CardAutoRequestConfigUnavailableError extends Error {
  reason: 'forbidden' | 'unavailable'

  constructor(reason: 'forbidden' | 'unavailable') {
    super(reason === 'forbidden' ? 'Недостаточно прав' : 'Модуль недоступен')
    this.reason = reason
  }
}

const url = (walletId: number) => `/api/corporate-card/auto-request-configs/${walletId}/`

async function readConfig(res: Response): Promise<CardAutoRequestConfigResponse> {
  if (res.status === 403) throw new CardAutoRequestConfigUnavailableError('forbidden')
  if (res.status === 404) throw new CardAutoRequestConfigUnavailableError('unavailable')
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as CardAutoRequestConfigResponse | null
  if (!json) throw new Error('Пустой ответ от сервера')
  return json
}

export async function getCardAutoRequestConfig(walletId: number): Promise<CardAutoRequestConfigResponse> {
  return readConfig(await apiFetch(url(walletId)))
}

export async function saveCardAutoRequestConfig(
  walletId: number,
  dto: CardAutoRequestConfigDto,
): Promise<CardAutoRequestConfigResponse> {
  return readConfig(
    await apiFetch(url(walletId), {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(dto),
    }),
  )
}
