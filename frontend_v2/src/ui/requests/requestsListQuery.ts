import dayjs from 'dayjs'
import { mobileStatusOptionLabel } from '../../lib/requestStatusLabels'

/** Tabs of the mobile requests feed (`/requests?tab=…`). */
export type RequestsTab = 'waiting' | 'all' | 'my' | 'drafts'

export const REQUESTS_TABS: readonly RequestsTab[] = ['waiting', 'all', 'my', 'drafts']

/** The phone opens the requests waiting on the user unless the address names another tab. */
export const DEFAULT_REQUESTS_TAB: RequestsTab = 'waiting'

export function parseRequestsTab(raw: string | null | undefined): RequestsTab | null {
  return REQUESTS_TABS.includes(raw as RequestsTab) ? (raw as RequestsTab) : null
}

/**
 * Filters of the mobile feed: the same set as the desktop filter panel, one status at a time. Dates are YYYY-MM-DD.
 * `requesterName` only labels the chip; the request sends the id.
 */
export type MobileRequestsFilters = {
  search: string
  status?: string
  paymentType?: string
  urgency?: string
  currency?: string
  category?: string
  vendor?: string
  requester?: string
  requesterName?: string
  amountMin: number | null
  amountMax: number | null
  submittedFrom?: string
  submittedTo?: string
  billingFrom?: string
  billingTo?: string
  amortizedOnly: boolean
  payedMissingExpense: boolean
}

export const EMPTY_MOBILE_FILTERS: MobileRequestsFilters = {
  search: '',
  amountMin: null,
  amountMax: null,
  amortizedOnly: false,
  payedMissingExpense: false,
}

/**
 * Query parameters of `GET /api/requests/` that the desktop list sends (RequestsPage, listUrl). The mobile feed uses
 * the same names; a test keeps the two lists in step.
 */
export const DESKTOP_REQUESTS_LIST_PARAMS = [
  'submitted_from',
  'submitted_to',
  'billing_from',
  'billing_to',
  'vendor_search',
  'amortized_only',
  'payed_missing_expense',
  'status',
  'urgency',
  'payment_type',
  'currency',
  'category',
  'vendor',
  'requester',
  'amount_min',
  'amount_max',
  'search',
  'ordering',
] as const

const REQUESTS_LIST_PATH = '/api/requests/'

function text(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const trimmed = value.trim()
  return trimmed ? trimmed : undefined
}

function isoDate(value: unknown): string | undefined {
  const raw = text(value)
  return raw && /^\d{4}-\d{2}-\d{2}$/.test(raw) ? raw : undefined
}

function amount(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null
}

/** Filters read back from sessionStorage: anything malformed falls back to «not set». */
export function normalizeMobileFilters(raw: unknown): MobileRequestsFilters {
  const source = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {}
  return {
    search: typeof source.search === 'string' ? source.search : '',
    status: text(source.status),
    paymentType: text(source.paymentType),
    urgency: text(source.urgency),
    currency: text(source.currency),
    category: text(source.category),
    vendor: text(source.vendor),
    requester: text(source.requester),
    requesterName: text(source.requesterName),
    amountMin: amount(source.amountMin),
    amountMax: amount(source.amountMax),
    submittedFrom: isoDate(source.submittedFrom),
    submittedTo: isoDate(source.submittedTo),
    billingFrom: isoDate(source.billingFrom),
    billingTo: isoDate(source.billingTo),
    amortizedOnly: source.amortizedOnly === true,
    payedMissingExpense: source.payedMissingExpense === true,
  }
}

/**
 * List address of a tab of the mobile feed, or null when nothing is to be requested: «Ждут меня» comes from the
 * action items, and «Мои» without the user's id must not go out (an empty `requester` would list everyone's requests).
 * «Мои» sends `requester=<user id>` and «Черновики» `status=DRAFT`, overriding those filters.
 */
export function buildRequestsListUrl(
  tab: RequestsTab,
  filters: MobileRequestsFilters,
  userId: number | null | undefined,
): string | null {
  if (tab === 'waiting') return null
  if (tab === 'my' && (typeof userId !== 'number' || !Number.isFinite(userId) || userId <= 0)) return null

  const params = new URLSearchParams()
  if (filters.submittedFrom) params.set('submitted_from', filters.submittedFrom)
  if (filters.submittedTo) params.set('submitted_to', filters.submittedTo)
  if (filters.billingFrom) params.set('billing_from', filters.billingFrom)
  if (filters.billingTo) params.set('billing_to', filters.billingTo)
  if (filters.amortizedOnly) params.set('amortized_only', '1')
  if (filters.payedMissingExpense) params.set('payed_missing_expense', '1')
  const status = tab === 'drafts' ? 'DRAFT' : filters.status
  if (status) params.set('status', status)
  if (filters.urgency) params.set('urgency', filters.urgency)
  if (filters.paymentType) params.set('payment_type', filters.paymentType)
  if (filters.currency) params.set('currency', filters.currency)
  if (filters.category) params.set('category', filters.category)
  if (filters.vendor) params.set('vendor', filters.vendor)
  const requester = tab === 'my' ? String(userId) : filters.requester
  if (requester) params.set('requester', requester)
  if (filters.amountMin !== null) params.set('amount_min', String(filters.amountMin))
  if (filters.amountMax !== null) params.set('amount_max', String(filters.amountMax))
  const search = filters.search.trim()
  if (search) params.set('search', search)
  const query = params.toString()
  return query ? `${REQUESTS_LIST_PATH}?${query}` : REQUESTS_LIST_PATH
}

/** A chip of an applied filter; `key` names what its cross clears. */
export type FilterChipKey =
  | 'status'
  | 'paymentType'
  | 'urgency'
  | 'currency'
  | 'category'
  | 'vendor'
  | 'requester'
  | 'amount'
  | 'submitted'
  | 'billing'
  | 'amortizedOnly'
  | 'payedMissingExpense'

export type FilterChip = { key: FilterChipKey; label: string }

function formatDay(value: string): string {
  return dayjs(value).format('DD.MM.YYYY')
}

function formatMonth(value: string): string {
  return dayjs(value).format('MM.YYYY')
}

function formatAmount(value: number): string {
  return value.toLocaleString('ru-RU')
}

function rangeLabel(from: string | undefined, to: string | undefined, format: (value: string) => string): string {
  if (from && to) return `${format(from)} – ${format(to)}`
  if (from) return `с ${format(from)}`
  return `по ${format(to as string)}`
}

/**
 * Chips of the applied filters, in the order of the sheet. The search has its own field and makes no chip; a filter the
 * tab overrides («Черновики» — status, «Мои» — requester) makes none either.
 */
export function activeFilterChips(filters: MobileRequestsFilters, tab: RequestsTab = 'all'): FilterChip[] {
  const chips: FilterChip[] = []
  if (filters.status && tab !== 'drafts') chips.push({ key: 'status', label: mobileStatusOptionLabel(filters.status) })
  if (filters.paymentType) chips.push({ key: 'paymentType', label: filters.paymentType })
  if (filters.urgency) chips.push({ key: 'urgency', label: filters.urgency })
  if (filters.currency) chips.push({ key: 'currency', label: filters.currency })
  if (filters.category) chips.push({ key: 'category', label: filters.category })
  if (filters.vendor) chips.push({ key: 'vendor', label: filters.vendor })
  if (filters.requester && tab !== 'my') {
    chips.push({ key: 'requester', label: filters.requesterName || `Заявитель #${filters.requester}` })
  }
  if (filters.amountMin !== null || filters.amountMax !== null) {
    const parts: string[] = []
    if (filters.amountMin !== null) parts.push(`от ${formatAmount(filters.amountMin)}`)
    if (filters.amountMax !== null) parts.push(`до ${formatAmount(filters.amountMax)}`)
    chips.push({ key: 'amount', label: `Сумма ${parts.join(' ')}` })
  }
  if (filters.submittedFrom || filters.submittedTo) {
    chips.push({ key: 'submitted', label: `Отправлено ${rangeLabel(filters.submittedFrom, filters.submittedTo, formatDay)}` })
  }
  if (filters.billingFrom || filters.billingTo) {
    chips.push({ key: 'billing', label: `Биллинг ${rangeLabel(filters.billingFrom, filters.billingTo, formatMonth)}` })
  }
  if (filters.amortizedOnly) chips.push({ key: 'amortizedOnly', label: 'С амортизацией' })
  if (filters.payedMissingExpense) chips.push({ key: 'payedMissingExpense', label: 'Оплачена без расхода' })
  return chips
}

/** Number on the filter button: how many chips the applied filters make. */
export function countActiveFilters(filters: MobileRequestsFilters, tab: RequestsTab = 'all'): number {
  return activeFilterChips(filters, tab).length
}

/** The filters without the one a chip's cross clears. */
export function removeFilterChip(filters: MobileRequestsFilters, key: FilterChipKey): MobileRequestsFilters {
  switch (key) {
    case 'amount':
      return { ...filters, amountMin: null, amountMax: null }
    case 'submitted':
      return { ...filters, submittedFrom: undefined, submittedTo: undefined }
    case 'billing':
      return { ...filters, billingFrom: undefined, billingTo: undefined }
    case 'requester':
      return { ...filters, requester: undefined, requesterName: undefined }
    case 'amortizedOnly':
      return { ...filters, amortizedOnly: false }
    case 'payedMissingExpense':
      return { ...filters, payedMissingExpense: false }
    default:
      return { ...filters, [key]: undefined }
  }
}

/** All filters cleared; `keepSearch` leaves the search text (the sheet's «Сбросить» does not touch it). */
export function clearFilters(filters: MobileRequestsFilters, keepSearch = false): MobileRequestsFilters {
  return { ...EMPTY_MOBILE_FILTERS, search: keepSearch ? filters.search : '' }
}
