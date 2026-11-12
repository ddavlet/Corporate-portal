import type { NavigateFunction } from 'react-router-dom'

/** Addresses of the phone «Инвестиции»: the section and its full-screen forms. */
export const INVESTMENTS_PATH = '/investments'
export const INVEST_RETURN_NEW_PATH = '/investments/returns/new'
export const INVESTMENT_COLLECT_PATH = '/investments/collect'
export const INVESTMENT_NEW_PATH = '/investments/new'

/**
 * Leaves a full-screen investments form: back to the earlier page of the portal in this tab (it keeps its state),
 * else (opened by a link) to `/investments` in place of the form. `depth` is the number of history entries the form
 * itself pushed before the current one (the wizard's steps), so they are left too and `/investments` is not added
 * to the history a second time.
 */
export function closeToInvestments(navigate: NavigateFunction, depth = 0): void {
  const idx = (window.history.state as { idx?: number } | null)?.idx
  if (typeof idx === 'number' && idx > depth) navigate(-(depth + 1))
  else navigate(INVESTMENTS_PATH, { replace: true })
}
