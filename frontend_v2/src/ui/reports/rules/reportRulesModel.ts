import type { ReportRules } from '../../../lib/reportsApi'

/** Investor payout types (backend `InvestReturn.ReturnType`); every type goes to exactly one section. */
export const INVEST_RETURN_TYPES = [
  { value: 'дивиденды', label: 'Дивиденды' },
  { value: 'проценты', label: 'Проценты' },
  { value: 'доля_прибыли', label: 'Доля прибыли' },
  { value: 'тело_инвестиций', label: 'Тело инвестиций' },
] as const

export type InvestBucket = 'operational' | 'other' | 'invest_returns'

export const INVEST_BUCKET_OPTIONS: { value: InvestBucket; label: string }[] = [
  { value: 'operational', label: 'Операционные расходы' },
  { value: 'other', label: 'Прочие расходы' },
  { value: 'invest_returns', label: 'Третья корзина (invest_returns)' },
]

export const PURPOSE_BUCKETS = ['purposeOperational', 'purposeOther', 'purposeInvestReturns'] as const
export type PurposeBucket = (typeof PURPOSE_BUCKETS)[number]

/** The rules as the admin edits them; lists typed one per line are kept as text. */
export type ReportRulesFormValues = {
  startMonth: string
  openingBalance: string
  cashExclude: string
  bankExclude: string
  requestExclude: string
  requestPaymentTypes: string[]
  purposeOperational: string[]
  purposeOther: string[]
  purposeInvestReturns: string[]
  investBucketByType: Record<string, InvestBucket>
}

export function splitList(text: string): string[] {
  return text
    .split(/[\n,]+/)
    .map((s) => s.trim())
    .filter(Boolean)
}

function joinList(items: string[] | undefined): string {
  return (items ?? []).join('\n')
}

export function uniqTrimmedStrings(items: Iterable<string>): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const x of items) {
    const s = String(x ?? '').trim()
    if (!s || seen.has(s)) continue
    seen.add(s)
    out.push(s)
  }
  return out
}

function hasFullInvestPartition(rules: ReportRules): boolean {
  const assigned = new Set([
    ...(rules.invest_return_type_operational ?? []),
    ...(rules.invest_return_type_other ?? []),
    ...(rules.invest_return_type_invest_returns ?? []),
  ])
  return INVEST_RETURN_TYPES.every((type) => assigned.has(type.value))
}

function investBucketsFromRules(rules: ReportRules): Record<string, InvestBucket> {
  const out: Record<string, InvestBucket> = {}
  for (const type of INVEST_RETURN_TYPES) {
    if ((rules.invest_return_type_operational ?? []).includes(type.value)) out[type.value] = 'operational'
    else if ((rules.invest_return_type_other ?? []).includes(type.value)) out[type.value] = 'other'
    else if ((rules.invest_return_type_invest_returns ?? []).includes(type.value)) out[type.value] = 'invest_returns'
    else out[type.value] = 'operational'
  }
  return out
}

/** A valid split for rules that have none yet (form defaults). */
export function defaultInvestBuckets(): Record<string, InvestBucket> {
  return {
    дивиденды: 'invest_returns',
    проценты: 'operational',
    доля_прибыли: 'operational',
    тело_инвестиций: 'other',
  }
}

/** Saved rules → form fields. */
export function formFromRules(rules: ReportRules): ReportRulesFormValues {
  return {
    startMonth: (rules.start_month ?? '').trim(),
    openingBalance: String(rules.opening_balance ?? '').trim(),
    cashExclude: joinList(rules.cash_exclude_operations),
    bankExclude: joinList(rules.bank_exclude_purposes),
    requestExclude: joinList(rules.request_exclude_categories),
    requestPaymentTypes: [...(rules.request_payment_types_for_pnl ?? [])],
    purposeOperational: uniqTrimmedStrings(rules.payment_purpose_operational ?? []),
    purposeOther: uniqTrimmedStrings(rules.payment_purpose_other ?? []),
    purposeInvestReturns: uniqTrimmedStrings(rules.payment_purpose_invest_returns ?? []),
    investBucketByType: hasFullInvestPartition(rules) ? investBucketsFromRules(rules) : defaultInvestBuckets(),
  }
}

/** Form fields → rules to save. Bank exclusions are sent only for a report that applies them (PnL). */
export function buildRulesFromForm(values: ReportRulesFormValues, options: { bankExclusions: boolean }): ReportRules {
  const operational: string[] = []
  const other: string[] = []
  const investReturns: string[] = []
  for (const type of INVEST_RETURN_TYPES) {
    const bucket = values.investBucketByType[type.value] ?? 'operational'
    if (bucket === 'operational') operational.push(type.value)
    else if (bucket === 'other') other.push(type.value)
    else investReturns.push(type.value)
  }
  return {
    start_month: values.startMonth.trim(),
    opening_balance: values.openingBalance.trim() || '0',
    cash_exclude_operations: splitList(values.cashExclude),
    ...(options.bankExclusions ? { bank_exclude_purposes: splitList(values.bankExclude) } : {}),
    request_exclude_categories: splitList(values.requestExclude),
    request_payment_types_for_pnl: [...values.requestPaymentTypes],
    payment_purpose_operational: uniqTrimmedStrings(values.purposeOperational),
    payment_purpose_other: uniqTrimmedStrings(values.purposeOther),
    payment_purpose_invest_returns: uniqTrimmedStrings(values.purposeInvestReturns),
    invest_return_type_operational: operational,
    invest_return_type_other: other,
    invest_return_type_invest_returns: investReturns,
  }
}

/** A payment purpose belongs to one section: picking it in one list takes it out of the other two. */
export function movePurposes(values: ReportRulesFormValues, bucket: PurposeBucket, picked: string[]): ReportRulesFormValues {
  const next: ReportRulesFormValues = { ...values }
  next[bucket] = picked
  for (const other of PURPOSE_BUCKETS) {
    if (other !== bucket) next[other] = values[other].filter((purpose) => !picked.includes(purpose))
  }
  return next
}
