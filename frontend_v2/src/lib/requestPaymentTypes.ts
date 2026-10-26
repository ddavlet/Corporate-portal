/** Canonical request payment types (must match backend ``Request.PAYMENT_TYPE_*``). */
export const REQUEST_PAYMENT_TYPES = [
  'Наличные',
  'Перечисление',
  'Пополнение',
  'Платежная карта',
  'Начисление ЗП',
  'Инвест. наличные',
  'Инвест. перечисление',
] as const

export type RequestPaymentType = (typeof REQUEST_PAYMENT_TYPES)[number]

export function requestPaymentTypeSelectOptions(): { value: RequestPaymentType; label: RequestPaymentType }[] {
  return REQUEST_PAYMENT_TYPES.map((value) => ({ value, label: value }))
}

/** Инвест-типы: доступны только при включённом инвестиционном режиме тенанта. */
export const INVEST_REQUEST_PAYMENT_TYPES: readonly RequestPaymentType[] = ['Инвест. наличные', 'Инвест. перечисление']

export function isInvestPaymentType(pt: string): boolean {
  return (INVEST_REQUEST_PAYMENT_TYPES as readonly string[]).includes(pt)
}

/** Валюта, зафиксированная подсказкой списания; null — у типа валюта не фиксируется (выбирает заявитель). */
export function lockedCurrencyFromHint(hint: { currency?: string | null } | null | undefined): string | null {
  return hint?.currency || null
}
