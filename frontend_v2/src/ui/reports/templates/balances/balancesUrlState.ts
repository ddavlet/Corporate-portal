import dayjs from 'dayjs'
import type { AccountBalancesQuery } from '../../../../lib/reportsApi'

/** «Период» shows a range; «На дату» everything from the account's first operation up to one day. */
export type BalancesMode = 'period' | 'date'

export type BalancesUrlState = {
  mode: BalancesMode
  wallet: number | null
  /** YYYY-MM-DD; unused in «На дату». */
  start: string
  end: string
}

const ISO = 'YYYY-MM-DD'

function isoDate(value: string | null): string | null {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null
  const parsed = dayjs(value)
  return parsed.isValid() && parsed.format(ISO) === value ? value : null
}

/** Defaults: this month up to today. Parameter names differ from the statement templates' `from`/`to`. */
export function readBalancesState(params: URLSearchParams, today = dayjs()): BalancesUrlState {
  const end = isoDate(params.get('end')) ?? today.format(ISO)
  const start = isoDate(params.get('start')) ?? dayjs(end).startOf('month').format(ISO)
  const wallet = Number(params.get('wallet'))
  return {
    mode: params.get('mode') === 'date' ? 'date' : 'period',
    wallet: Number.isInteger(wallet) && wallet > 0 ? wallet : null,
    start: start <= end ? start : end,
    end,
  }
}

export function writeBalancesState(params: URLSearchParams, state: BalancesUrlState): URLSearchParams {
  const next = new URLSearchParams(params)
  next.set('mode', state.mode)
  next.set('end', state.end)
  if (state.mode === 'period') next.set('start', state.start)
  else next.delete('start')
  if (state.wallet) next.set('wallet', String(state.wallet))
  else next.delete('wallet')
  return next
}

export function toBalancesQuery(state: BalancesUrlState & { wallet: number }): AccountBalancesQuery {
  return { wallet: state.wallet, dateTo: state.end, dateFrom: state.mode === 'period' ? state.start : undefined }
}
