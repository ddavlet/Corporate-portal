/** Canonical request payment types (must match backend ``Request.PAYMENT_TYPE_*``). */
export const REQUEST_PAYMENT_TYPES = [
  'Наличные',
  'Перечисление',
  'Пополнение',
  'Платежная карта',
  'Начисление ЗП',
] as const

export type RequestPaymentType = (typeof REQUEST_PAYMENT_TYPES)[number]

export function requestPaymentTypeSelectOptions(): { value: RequestPaymentType; label: RequestPaymentType }[] {
  return REQUEST_PAYMENT_TYPES.map((value) => ({ value, label: value }))
}
