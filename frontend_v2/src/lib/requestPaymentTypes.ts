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

/** Наличные-семейство: «Наличные» и «Инвест. наличные» (как backend ``cash_like_payment_types``). */
const CASH_FAMILY_PAYMENT_TYPES: readonly string[] = ['Наличные', 'Инвест. наличные']

/** Вид поставщика по типу оплаты (как backend ``payment_type_to_vendor_kind``). */
export function vendorKindForPaymentType(pt: string): 'cash' | 'transfer' {
  return CASH_FAMILY_PAYMENT_TYPES.includes(pt) ? 'cash' : 'transfer'
}

/** Убирает инвест-типы, если инвестиционный режим тенанта выключен. */
export function withoutInvestTypesUnlessEnabled<T>(
  items: readonly T[],
  paymentTypeOf: (item: T) => string,
  investModeEnabled: boolean,
): T[] {
  if (investModeEnabled) return [...items]
  return items.filter((item) => !isInvestPaymentType(paymentTypeOf(item)))
}

/**
 * Варианты типов оплаты для правил отчётов: инвест-типы не предлагаются (backend подключает их
 * автоматически к «Наличные»/«Перечисление»), но уже сохранённые значения остаются в списке,
 * чтобы не пропасть из выбора.
 */
export function reportRulePaymentTypeOptions(
  selected: readonly string[] = [],
): { value: string; label: string }[] {
  const base: { value: string; label: string }[] = withoutInvestTypesUnlessEnabled(
    requestPaymentTypeSelectOptions(),
    (o) => o.value,
    false,
  )
  const savedInvest = INVEST_REQUEST_PAYMENT_TYPES.filter((pt) => selected.includes(pt))
  return [...base, ...savedInvest.map((value) => ({ value, label: value }))]
}

/** Валюта, зафиксированная подсказкой списания; null — у типа валюта не фиксируется (выбирает заявитель). */
export function lockedCurrencyFromHint(hint: { currency?: string | null } | null | undefined): string | null {
  return hint?.currency || null
}
