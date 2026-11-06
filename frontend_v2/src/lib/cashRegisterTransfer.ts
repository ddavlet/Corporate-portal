import dayjs from 'dayjs'
import { setCashRegisterTransferTarget } from './cashDeskApi'
import { createPortalRequest, submitRequestForApproval, type CashRegisterDto } from './api'

export const CASH_REGISTER_TRANSFER_PAYMENT_TYPE = 'Наличные'
export const CASH_REGISTER_TRANSFER_PAYMENT_PURPOSE = 'Перевод между кассами'

export function cashRegisterLabel(r: CashRegisterDto): string {
  return (r.name || '').trim() || r.currency
}

/** Заявка создана, но не отправлена на согласование — черновик уже существует под `requestId`. */
export class CashRegisterTransferSubmitError extends Error {
  requestId: number

  constructor(requestId: number, cause: unknown) {
    super(cause instanceof Error ? cause.message : 'ошибка')
    this.requestId = requestId
  }
}

function isNotFound(err: unknown): boolean {
  return typeof err === 'object' && err !== null && (err as { status?: unknown }).status === 404
}

export type CashRegisterTransferInput = {
  fromRegister: CashRegisterDto
  toRegister: CashRegisterDto
  amount: number
  note?: string
  toAmount?: number
  requesterId?: number | null
}

/** Создаёт заявку типа "Наличные"/"Перевод между кассами" и сразу отправляет её на согласование. */
export async function submitCashRegisterTransfer({
  fromRegister,
  toRegister,
  amount,
  note,
  toAmount,
  requesterId,
}: CashRegisterTransferInput): Promise<{ id: number }> {
  const crossCurrency = fromRegister.currency !== toRegister.currency
  if (crossCurrency && !(typeof toAmount === 'number' && toAmount > 0)) {
    throw new Error('Укажите сумму зачисления')
  }
  const fromLabel = cashRegisterLabel(fromRegister)
  const toLabel = cashRegisterLabel(toRegister)
  const descriptionLines = [
    'Перевод ДС между кассами.',
    `Из кассы: ${fromLabel} (${fromRegister.currency})`,
    `В кассу: ${toLabel} (${toRegister.currency})`,
  ]
  if (crossCurrency) descriptionLines.push(`Сумма зачисления: ${toAmount} ${toRegister.currency}`)
  const trimmedNote = (note || '').trim()
  if (trimmedNote) descriptionLines.push(`Примечание: ${trimmedNote}`)

  const created = await createPortalRequest({
    title: `Перевод: ${fromLabel} → ${toLabel}`,
    description: descriptionLines.join('\n'),
    amount,
    currency: fromRegister.currency,
    payment_type: CASH_REGISTER_TRANSFER_PAYMENT_TYPE,
    payment_purpose: CASH_REGISTER_TRANSFER_PAYMENT_PURPOSE,
    urgency: 'Обычно',
    billing_date: dayjs().format('YYYY-MM-DD'),
    status: 'DRAFT',
    amortization_months: 1,
    wallet_ref: fromRegister.wallet_id,
    ...(requesterId != null ? { requester: requesterId } : {}),
  })

  try {
    await setCashRegisterTransferTarget(created.id, {
      to_wallet_id: toRegister.wallet_id,
      ...(crossCurrency ? { to_amount: toAmount } : {}),
    })
  } catch (err: unknown) {
    // Модуль «Касса» недоступен (404): при одной валюте приход найдётся по строке «В кассу: …» в описании.
    if (crossCurrency || !isNotFound(err)) {
      throw new CashRegisterTransferSubmitError(created.id, err)
    }
  }

  try {
    await submitRequestForApproval(created.id)
  } catch (err: unknown) {
    throw new CashRegisterTransferSubmitError(created.id, err)
  }

  return { id: created.id }
}
