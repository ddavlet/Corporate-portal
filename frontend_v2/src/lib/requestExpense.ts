/** Фрагмент expense_link из API заявки */
export type RequestExpenseLink = {
  module?: string
  expense_type?: string
  id?: number | string
  doc_id?: string
  url?: string | null
} | null

const PORTAL_EXPENSE_MODULES = ['cash', 'bank', 'payroll'] as const

/**
 * Статус PAYED, но связь не на кассу/банк/начисления ЗП:
 * нет expense_link, или только внешний fallback (module === "external").
 * module payroll / corporate_card считаются валидной связью.
 */
export function isPayedMissingLinkedExpense(row: {
  status: string
  expense_link?: RequestExpenseLink
}): boolean {
  if (String(row.status || '').trim().toUpperCase() !== 'PAYED') return false
  const link = row.expense_link
  if (link == null) return true
  if (link.module === 'external') return true
  if (['cash', 'bank', 'payroll', 'corporate_card'].includes(String(link.module || ''))) return false
  return true
}

/** Можно открыть карточку расхода во фронте (есть маршрут с id). */
export function canOpenLinkedExpense(link: RequestExpenseLink): boolean {
  if (!link || link.id == null || link.id === '') return false
  return PORTAL_EXPENSE_MODULES.includes(link.module as (typeof PORTAL_EXPENSE_MODULES)[number])
}

/** SPA-путь к связанному расходу; API `expense_link.url` не использовать в UI. */
export function linkedExpenseFrontendPath(
  link: RequestExpenseLink,
  options?: { telegram?: boolean },
): string | null {
  if (!canOpenLinkedExpense(link)) return null
  const expId = String(link!.id)
  const tg = Boolean(options?.telegram)
  if (link!.module === 'cash') return tg ? `/tg/cash/expenses/${expId}` : `/cash/expenses/${expId}`
  if (link!.module === 'bank') return tg ? `/tg/bank/expenses/${expId}` : `/bank/expenses/${expId}`
  if (link!.module === 'payroll') return `/payroll/${expId}`
  return null
}

const MODULE_LABELS: Record<string, string> = {
  cash: 'Касса',
  bank: 'Банк',
  payroll: 'Начисление ЗП',
  corporate_card: 'Корпоративная карта',
  external: 'Внешний платёж',
}

/** Понятная подпись связанного расхода для карточки заявки. */
export function linkedExpenseLabel(link: RequestExpenseLink): string | null {
  if (!link) return null
  const moduleKey = String(link.module || '').trim()
  if (!moduleKey) return null
  const moduleTitle = MODULE_LABELS[moduleKey] || moduleKey
  if (moduleKey === 'payroll' && link.doc_id != null && String(link.doc_id).trim() !== '') {
    return `${moduleTitle} · документ ${String(link.doc_id).trim()}`
  }
  if (moduleKey === 'external') {
    const extId = link.id != null && link.id !== '' ? String(link.id) : '—'
    return `${moduleTitle} · ID ${extId}`
  }
  if (link.id != null && link.id !== '') {
    return `${moduleTitle} · #${link.id}`
  }
  return moduleTitle
}
