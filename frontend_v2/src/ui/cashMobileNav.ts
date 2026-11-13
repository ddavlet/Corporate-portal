import type { NavigateFunction } from 'react-router-dom'

/** Addresses of the phone «Касса»: the section and its full-screen transfer form. */
export const CASH_PATH = '/cash'
export const CASH_TRANSFER_PATH = '/cash/transfer'

/**
 * Leaves the full-screen transfer form: back to the earlier page of the portal in this tab (it keeps its state),
 * else (opened by a link) to `/cash` in place of the form, as closeToInvestments does for the investments forms.
 */
export function closeToCash(navigate: NavigateFunction): void {
  const idx = (window.history.state as { idx?: number } | null)?.idx
  if (typeof idx === 'number' && idx > 0) navigate(-1)
  else navigate(CASH_PATH, { replace: true })
}
