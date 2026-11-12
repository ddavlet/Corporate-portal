import { describe, expect, it } from 'vitest'
import requestsPageSource from './RequestsPage.tsx?raw'
import {
  DESKTOP_REQUESTS_LIST_PARAMS,
  EMPTY_MOBILE_FILTERS,
  activeFilterChips,
  buildRequestsListUrl,
  clearFilters,
  countActiveFilters,
  normalizeMobileFilters,
  parseRequestsTab,
  removeFilterChip,
  type MobileRequestsFilters,
} from './requestsListQuery'

function query(url: string | null): Record<string, string> {
  expect(url).not.toBeNull()
  const [path, search = ''] = String(url).split('?')
  expect(path).toBe('/api/requests/')
  return Object.fromEntries(new URLSearchParams(search))
}

const FULL: MobileRequestsFilters = {
  search: '  аренда  ',
  status: '2',
  paymentType: 'Перечисление',
  urgency: 'Срочно',
  currency: 'USD',
  category: 'Офис',
  vendor: 'ООО Альфа',
  requester: '7',
  requesterName: 'ivanov',
  amountMin: 100,
  amountMax: 5000,
  submittedFrom: '2026-11-01',
  submittedTo: '2026-11-10',
  billingFrom: '2026-10-01',
  billingTo: '2026-11-30',
  amortizedOnly: true,
  payedMissingExpense: true,
}

describe('buildRequestsListUrl', () => {
  it('lists every request on «Все» without filters', () => {
    expect(buildRequestsListUrl('all', EMPTY_MOBILE_FILTERS, 5)).toBe('/api/requests/')
  })

  it('adds requester=<user id> on «Мои» and status=DRAFT on «Черновики»', () => {
    expect(query(buildRequestsListUrl('my', EMPTY_MOBILE_FILTERS, 42))).toEqual({ requester: '42' })
    expect(query(buildRequestsListUrl('drafts', EMPTY_MOBILE_FILTERS, 42))).toEqual({ status: 'DRAFT' })
  })

  it('never asks for «Мои» without the user id (an empty requester would list everyone)', () => {
    expect(buildRequestsListUrl('my', EMPTY_MOBILE_FILTERS, null)).toBeNull()
    expect(buildRequestsListUrl('my', EMPTY_MOBILE_FILTERS, undefined)).toBeNull()
    expect(buildRequestsListUrl('my', EMPTY_MOBILE_FILTERS, 0)).toBeNull()
    expect(buildRequestsListUrl('my', { ...EMPTY_MOBILE_FILTERS, requester: '9' }, null)).toBeNull()
  })

  it('requests nothing for «Ждут меня» (it comes from the action items)', () => {
    expect(buildRequestsListUrl('waiting', FULL, 5)).toBeNull()
  })

  it('sends every filter under the desktop parameter names', () => {
    expect(query(buildRequestsListUrl('all', FULL, 5))).toEqual({
      submitted_from: '2026-11-01',
      submitted_to: '2026-11-10',
      billing_from: '2026-10-01',
      billing_to: '2026-11-30',
      amortized_only: '1',
      payed_missing_expense: '1',
      status: '2',
      urgency: 'Срочно',
      payment_type: 'Перечисление',
      currency: 'USD',
      category: 'Офис',
      vendor: 'ООО Альфа',
      requester: '7',
      amount_min: '100',
      amount_max: '5000',
      search: 'аренда',
    })
  })

  it('lets the tab override the status and the requester filters', () => {
    expect(query(buildRequestsListUrl('my', FULL, 42)).requester).toBe('42')
    expect(query(buildRequestsListUrl('drafts', FULL, 42)).status).toBe('DRAFT')
  })

  it('keeps an amount of zero', () => {
    expect(query(buildRequestsListUrl('all', { ...EMPTY_MOBILE_FILTERS, amountMin: 0 }, 1))).toEqual({ amount_min: '0' })
  })

  it('uses only parameter names the desktop list sends', () => {
    const desktopNames = [...requestsPageSource.matchAll(/params\.set\('([a-z_]+)'/g)].map((m) => m[1])
    expect(new Set(desktopNames)).toEqual(new Set(DESKTOP_REQUESTS_LIST_PARAMS))
    const mobileNames = Object.keys(query(buildRequestsListUrl('all', FULL, 5)))
    for (const name of mobileNames) expect(DESKTOP_REQUESTS_LIST_PARAMS).toContain(name)
  })
})

describe('parseRequestsTab', () => {
  it('accepts the four tabs only', () => {
    expect(parseRequestsTab('waiting')).toBe('waiting')
    expect(parseRequestsTab('drafts')).toBe('drafts')
    expect(parseRequestsTab('other')).toBeNull()
    expect(parseRequestsTab(null)).toBeNull()
  })
})

describe('filter chips', () => {
  it('makes a chip per applied filter and counts them', () => {
    const filters: MobileRequestsFilters = { ...EMPTY_MOBILE_FILTERS, status: 'PAYED', currency: 'USD', amortizedOnly: true }
    expect(activeFilterChips(filters).map((c) => c.label)).toEqual(['Оплачена', 'USD', 'С амортизацией'])
    expect(countActiveFilters(filters)).toBe(3)
  })

  it('makes no chip for the search and none without filters', () => {
    expect(activeFilterChips({ ...EMPTY_MOBILE_FILTERS, search: 'аренда' })).toEqual([])
    expect(countActiveFilters(EMPTY_MOBILE_FILTERS)).toBe(0)
  })

  it('labels ranges, the requester and the switches', () => {
    const labels = activeFilterChips(FULL).map((c) => c.label)
    expect(labels).toEqual([
      'Шаг 2',
      'Перечисление',
      'Срочно',
      'USD',
      'Офис',
      'ООО Альфа',
      'ivanov',
      `Сумма от ${(100).toLocaleString('ru-RU')} до ${(5000).toLocaleString('ru-RU')}`,
      'Отправлено 01.11.2026 – 10.11.2026',
      'Биллинг 10.2026 – 11.2026',
      'С амортизацией',
      'Оплачена без расхода',
    ])
    expect(countActiveFilters(FULL)).toBe(12)
    expect(activeFilterChips({ ...EMPTY_MOBILE_FILTERS, submittedFrom: '2026-11-01' })[0].label).toBe(
      'Отправлено с 01.11.2026',
    )
    expect(activeFilterChips({ ...EMPTY_MOBILE_FILTERS, amountMax: 10 })[0].label).toBe('Сумма до 10')
  })

  it('skips the filters the tab overrides', () => {
    expect(activeFilterChips(FULL, 'drafts').some((c) => c.key === 'status')).toBe(false)
    expect(activeFilterChips(FULL, 'my').some((c) => c.key === 'requester')).toBe(false)
    expect(countActiveFilters(FULL, 'drafts')).toBe(11)
  })

  it('clears one filter from its chip', () => {
    expect(removeFilterChip(FULL, 'currency').currency).toBeUndefined()
    const noAmount = removeFilterChip(FULL, 'amount')
    expect([noAmount.amountMin, noAmount.amountMax]).toEqual([null, null])
    const noRequester = removeFilterChip(FULL, 'requester')
    expect([noRequester.requester, noRequester.requesterName]).toEqual([undefined, undefined])
    expect(removeFilterChip(FULL, 'payedMissingExpense').payedMissingExpense).toBe(false)
    expect(countActiveFilters(removeFilterChip(FULL, 'billing'))).toBe(11)
  })

  it('clears everything, keeping the search only when asked', () => {
    expect(clearFilters(FULL)).toEqual(EMPTY_MOBILE_FILTERS)
    expect(clearFilters(FULL, true)).toEqual({ ...EMPTY_MOBILE_FILTERS, search: FULL.search })
  })
})

describe('normalizeMobileFilters', () => {
  it('drops malformed values read back from storage', () => {
    expect(normalizeMobileFilters(null)).toEqual(EMPTY_MOBILE_FILTERS)
    expect(
      normalizeMobileFilters({ status: 5, currency: ' USD ', amountMin: -1, amountMax: '9', submittedFrom: '01.11.2026', amortizedOnly: 'yes' }),
    ).toEqual({ ...EMPTY_MOBILE_FILTERS, currency: 'USD' })
    expect(normalizeMobileFilters(FULL)).toEqual(FULL)
  })
})
