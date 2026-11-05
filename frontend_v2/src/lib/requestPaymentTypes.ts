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

/** Кошелёк списания из подсказки инвест-типа (``funding_hint`` в form-options). */
export type FundingHintWallet = { wallet_id: number; wallet_label: string; currency: string | null }

export type FundingHint = FundingHintWallet & {
  /** «Инвест. наличные»: все инвест-кассы режима (по одной на валюту), основная — первой. */
  wallets?: FundingHintWallet[]
}

type HintLike = { currency?: string | null; wallets?: { currency: string | null }[] } | null | undefined

/** Валюты, допустимые подсказкой списания (основная — первой); null — валюту выбирает заявитель. */
export function fundingCurrenciesFromHint(hint: HintLike): string[] | null {
  if (!hint) return null
  const fromWallets = (hint.wallets ?? []).map((w) => w.currency).filter((c): c is string => Boolean(c))
  if (fromWallets.length) return Array.from(new Set(fromWallets))
  return hint.currency ? [hint.currency] : null
}

/** Валюта, зафиксированная подсказкой списания; null — валюта не фиксируется (одна из нескольких или любая). */
export function lockedCurrencyFromHint(hint: HintLike): string | null {
  const currencies = fundingCurrenciesFromHint(hint)
  return currencies && currencies.length === 1 ? currencies[0] : null
}

/** Подпись кошелька списания для выбранной валюты: при нескольких инвест-кассах — касса этой валюты. */
export function fundingWalletLabel(hint: FundingHint | null | undefined, currency: string | null | undefined): string | null {
  if (!hint) return null
  const match = (hint.wallets ?? []).find((w) => w.currency === currency)
  return match ? match.wallet_label : hint.wallet_label
}
