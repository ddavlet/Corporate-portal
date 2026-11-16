import { useCallback, useSyncExternalStore } from 'react'
import { getPayrollCardAttention, type PayrollCardAttentionDto } from './payrollCardApi'

/**
 * Shared state of the card payouts review («Выплаты на карту: разбор»). The menu counter, the button in the payroll
 * list header and the review page read one module-level store, so the server is asked once per refresh.
 *
 * Refresh: on first use, when the window gets focus (at most once per 30 s) and explicitly after a link or an assign.
 * data is null when the user has no payroll role or the module is off (403/404). A failed refresh keeps the data
 * already loaded (the badge and the review stay) and only sets error; data is null after a failure only if nothing
 * was loaded before.
 */

export const PAYROLL_CARD_FOCUS_THROTTLE_MS = 30_000

export type PayrollCardAttentionState = {
  data: PayrollCardAttentionDto | null
  loading: boolean
  /** The last request failed (not 403/404). */
  error: string | null
}

const INITIAL_STATE: PayrollCardAttentionState = { data: null, loading: true, error: null }
const DISABLED_STATE: PayrollCardAttentionState = { data: null, loading: false, error: null }

let state: PayrollCardAttentionState = INITIAL_STATE
const listeners = new Set<() => void>()
let inflight: Promise<void> | null = null
let generation = 0
let lastStartedAt = 0

function setState(next: PayrollCardAttentionState) {
  state = next
  listeners.forEach((listener) => listener())
}

export function refreshPayrollCardAttention(): Promise<void> {
  if (inflight) return inflight
  const startedIn = generation
  lastStartedAt = Date.now()
  const request = getPayrollCardAttention()
    .then((data) => {
      if (startedIn === generation) setState({ data, loading: false, error: null })
    })
    .catch((e: unknown) => {
      if (startedIn !== generation) return
      // Keep what was loaded before: a background refresh failure must not wipe the badge or the review.
      setState({ data: state.data, loading: false, error: e instanceof Error ? e.message : 'Не удалось загрузить данные' })
    })
    .finally(() => {
      if (inflight === request) inflight = null
    })
  inflight = request
  return request
}

function onFocus() {
  if (Date.now() - lastStartedAt < PAYROLL_CARD_FOCUS_THROTTLE_MS) return
  void refreshPayrollCardAttention()
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  if (listeners.size === 1) {
    if (state === INITIAL_STATE || Date.now() - lastStartedAt >= PAYROLL_CARD_FOCUS_THROTTLE_MS) {
      void refreshPayrollCardAttention()
    }
    window.addEventListener('focus', onFocus)
  }
  return () => {
    listeners.delete(listener)
    if (listeners.size === 0) window.removeEventListener('focus', onFocus)
  }
}

const noopSubscribe = () => () => {}

function getSnapshot(): PayrollCardAttentionState {
  return state
}

function getDisabledSnapshot(): PayrollCardAttentionState {
  return DISABLED_STATE
}

/** Forgets the previous answer (tests, logout); answers already on the way are dropped. */
export function resetPayrollCardAttentionCache(): void {
  generation += 1
  inflight = null
  lastStartedAt = 0
  state = INITIAL_STATE
  listeners.forEach((listener) => listener())
}

/** Number to show on the badge and the header button: 0 when card accounting is off or not allowed. */
export function payrollCardAttentionCount(data: PayrollCardAttentionDto | null): number {
  return data?.enabled ? data.count : 0
}

/** enabled=false (no payroll module access) keeps the hook idle: no request, data null. */
export function usePayrollCardAttention(
  enabled = true,
): PayrollCardAttentionState & { count: number; refresh: () => Promise<void> } {
  const snapshot = useSyncExternalStore(
    enabled ? subscribe : noopSubscribe,
    enabled ? getSnapshot : getDisabledSnapshot,
    enabled ? getSnapshot : getDisabledSnapshot,
  )
  const refresh = useCallback(() => refreshPayrollCardAttention(), [])
  return { ...snapshot, count: payrollCardAttentionCount(snapshot.data), refresh }
}
