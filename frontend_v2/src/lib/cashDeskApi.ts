import { apiFetch, parseErrorBody } from './api'

export type CashDeskConfigDto = {
  is_active: boolean
  telegram_chat_id: number | null
}

export type CashDeskConfigResponse = CashDeskConfigDto & {
  options: { telegram_chats: Array<{ id: number; name: string }> }
}

export class CashDeskConfigUnavailableError extends Error {}

/** Ошибка HTTP модуля «Касса» с кодом ответа (404 — модуль недоступен/выключен). */
export class CashDeskApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

const CONFIG_URL = '/api/cash-desk/config/'

async function readConfig(res: Response): Promise<CashDeskConfigResponse> {
  if (res.status === 403 || res.status === 404) {
    throw new CashDeskConfigUnavailableError('Настройка недоступна')
  }
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as CashDeskConfigResponse | null
  if (!json) throw new Error('Пустой ответ от сервера')
  return json
}

export async function getCashDeskConfig(): Promise<CashDeskConfigResponse> {
  return readConfig(await apiFetch(CONFIG_URL))
}

export async function saveCashDeskConfig(dto: CashDeskConfigDto): Promise<CashDeskConfigResponse> {
  return readConfig(
    await apiFetch(CONFIG_URL, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(dto),
    }),
  )
}

/** Сохраняет кассу-получателя (и сумму зачисления при разных валютах) для заявки-перевода. */
export async function setCashRegisterTransferTarget(
  requestId: number,
  body: { to_wallet_id: number; to_amount?: number },
): Promise<void> {
  const res = await apiFetch(`/api/cash-desk/transfers/${requestId}/target/`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new CashDeskApiError(res.status, await parseErrorBody(res))
}
