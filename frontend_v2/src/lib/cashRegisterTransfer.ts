import dayjs from 'dayjs'
import { setCashRegisterTransferTarget } from './cashDeskApi'
import { createPortalRequest, submitRequestForApproval, type CashRegisterDto } from './api'

export const CASH_REGISTER_TRANSFER_PAYMENT_TYPE = 'Наличные'
export const CASH_REGISTER_TRANSFER_PAYMENT_PURPOSE = 'Перевод между кассами'

/** Назначение «Перевод между кассами» оформляется только кнопкой перевода: в общей форме нет поля кассы-получателя. */
export function isCashRegisterTransferPurpose(name: string | null | undefined): boolean {
  return (name || '').trim() === CASH_REGISTER_TRANSFER_PAYMENT_PURPOSE
}

/** Назначения для общей формы заявки без перевода между кассами; `transferHidden` — было ли оно в списке. */
export function generalFormPurposes<T extends { name: string }>(
  purposes: readonly T[] | null | undefined,
): { purposes: T[]; transferHidden: boolean } {
  const all = purposes ?? []
  const kept = all.filter((p) => !isCashRegisterTransferPurpose(p.name))
  return { purposes: kept, transferHidden: kept.length !== all.length }
}

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

/** Заявка уже ушла на согласование, но касса-получатель не сохранилась — приход может не создаться. */
export class CashRegisterTransferTargetError extends Error {
  requestId: number

  constructor(requestId: number, cause: unknown) {
    super(cause instanceof Error ? cause.message : 'ошибка')
    this.requestId = requestId
  }
}

/** Текст ошибки отправки перевода для формы. */
export function cashRegisterTransferErrorText(err: unknown): string {
  if (err instanceof CashRegisterTransferTargetError) {
    return (
      `Заявка №${err.requestId} отправлена на согласование, но касса-получатель не сохранена (${err.message.replace(/\.$/, '')}). ` +
      'Если после оплаты приход не появится, внесите его вручную.'
    )
  }
  if (err instanceof CashRegisterTransferSubmitError) {
    return `Заявка №${err.requestId} создана, но не отправлена на согласование: ${err.message}`
  }
  return err instanceof Error ? err.message : 'Не удалось создать заявку'
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

/** Создаёт заявку типа "Наличные"/"Перевод между кассами", сохраняет кассу-получателя и отправляет на согласование. */
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

  // При настроенных шагах согласования бэкенд отправляет заявку на согласование уже при создании.
  const alreadySubmitted = Boolean(created.status) && created.status !== 'DRAFT'

  try {
    await setCashRegisterTransferTarget(created.id, {
      to_wallet_id: toRegister.wallet_id,
      ...(crossCurrency ? { to_amount: toAmount } : {}),
    })
  } catch (err: unknown) {
    // Модуль «Касса» недоступен (404): при одной валюте приход найдётся по строке «В кассу: …» в описании.
    if (crossCurrency || !isNotFound(err)) {
      if (alreadySubmitted) throw new CashRegisterTransferTargetError(created.id, err)
      throw new CashRegisterTransferSubmitError(created.id, err)
    }
  }

  if (alreadySubmitted) return { id: created.id }

  try {
    await submitRequestForApproval(created.id)
  } catch (err: unknown) {
    throw new CashRegisterTransferSubmitError(created.id, err)
  }

  return { id: created.id }
}
