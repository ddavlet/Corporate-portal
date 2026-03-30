/** Фрагмент expense_link из API заявки */
export type RequestExpenseLink = {
  module?: string
  id?: number | string
  url?: string | null
} | null

/**
 * Статус PAYED, но связь не на кассу/банк/начисления ЗП:
 * нет expense_link, или только внешний fallback (module === "external").
 * module payroll считается валидной связью.
 */
export function isPayedMissingLinkedExpense(row: {
  status: string
  expense_link?: RequestExpenseLink
}): boolean {
  if (String(row.status || '').trim().toUpperCase() !== 'PAYED') return false
  const link = row.expense_link
  if (link == null) return true
  if (link.module === 'external') return true
  return false
}
