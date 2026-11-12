import { useCallback, useSyncExternalStore } from 'react'
import { actionItemTag, getActionItemsForPortal, type ActionItem } from './actionItemsApi'
import { syncAppBadge } from './appBadge'

/**
 * Shared "requires my action" counter. Every component that shows the count (menu, bell, notifications page) reads one
 * module-level store, so the server is asked once per refresh however many of them are on screen.
 *
 * On the shared app host the store holds the items of all the user's companies (count = their sum, tags carry the
 * company), so the menu badge, the bell and the icon badge show the total.
 *
 * Refresh: on first use, every 60 s while the tab is visible, and when the window gets focus or becomes visible.
 * After each answer the icon badge is synced and the service worker is told the current tags (it will close stale
 * system notifications once Web Push lands). A failed or forbidden request counts as zero.
 *
 * Backoff: after consecutive failures the timer skips ticks, waiting 2, 4, then at most 5 minutes between requests, so a
 * broken or forbidden endpoint is not hammered by every open tab. Focus and visibilitychange still ask right away; the
 * first successful answer restores the 60 s rhythm.
 */

export const ACTION_ITEMS_POLL_MS = 60_000
/** Focus and visibilitychange often fire together or right after page load: one request is enough. */
export const ACTION_ITEMS_FOCUS_THROTTLE_MS = 5_000
/** Upper bound of the wait between timer requests after repeated failures. */
export const ACTION_ITEMS_MAX_BACKOFF_MS = 300_000

export type ActionItemsState = {
  items: ActionItem[]
  count: number
  /** No answer yet since the first use (or since a reset). */
  loading: boolean
  /** The last refresh failed; count and items are zero. */
  error: boolean
}

const INITIAL_STATE: ActionItemsState = { items: [], count: 0, loading: true, error: false }

let state: ActionItemsState = INITIAL_STATE
const listeners = new Set<() => void>()
let inflight: Promise<void> | null = null
let generation = 0
let pollTimer: ReturnType<typeof setInterval> | null = null
let lastStartedAt = 0
let consecutiveFailures = 0

function setState(next: ActionItemsState) {
  state = next
  listeners.forEach((listener) => listener())
}

function notifyServiceWorker(items: ActionItem[], count: number) {
  try {
    const controller = typeof navigator !== 'undefined' ? navigator.serviceWorker?.controller : null
    controller?.postMessage({ type: 'action-items', tags: items.map(actionItemTag), count })
  } catch {
    // A worker that is going away must not break the counter.
  }
}

function applyResult(items: ActionItem[], count: number, error: boolean) {
  setState({ items, count, loading: false, error })
  syncAppBadge(count)
  // A failed request says nothing about which steps are closed: the worker keeps its notifications until a real answer.
  if (!error) notifyServiceWorker(items, count)
}

export function refreshActionItems(): Promise<void> {
  if (inflight) return inflight
  const startedIn = generation
  lastStartedAt = Date.now()
  const request = getActionItemsForPortal()
    .then((data) => {
      if (startedIn !== generation) return
      consecutiveFailures = 0
      applyResult(data.items, data.count, false)
    })
    .catch(() => {
      if (startedIn !== generation) return
      consecutiveFailures += 1
      applyResult([], 0, true)
    })
    .finally(() => {
      if (inflight === request) inflight = null
    })
  inflight = request
  return request
}

function isVisible(): boolean {
  return typeof document === 'undefined' || document.visibilityState !== 'hidden'
}

/** Wait before the next timer request: the poll interval, doubled per consecutive failure, capped. */
export function actionItemsPollDelay(failures: number): number {
  if (failures <= 0) return ACTION_ITEMS_POLL_MS
  return Math.min(ACTION_ITEMS_POLL_MS * 2 ** failures, ACTION_ITEMS_MAX_BACKOFF_MS)
}

function onPollTick() {
  if (!isVisible()) return
  // Half a tick of slack: setInterval may fire a few ms early relative to lastStartedAt.
  const due = actionItemsPollDelay(consecutiveFailures) - ACTION_ITEMS_POLL_MS / 2
  if (Date.now() - lastStartedAt < due) return
  void refreshActionItems()
}

function refreshOnReturn() {
  if (Date.now() - lastStartedAt < ACTION_ITEMS_FOCUS_THROTTLE_MS) return
  void refreshActionItems()
}

function onFocus() {
  refreshOnReturn()
}

function onVisibilityChange() {
  if (isVisible()) refreshOnReturn()
}

function start() {
  void refreshActionItems()
  pollTimer = setInterval(onPollTick, ACTION_ITEMS_POLL_MS)
  window.addEventListener('focus', onFocus)
  document.addEventListener('visibilitychange', onVisibilityChange)
}

function stop() {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
  window.removeEventListener('focus', onFocus)
  document.removeEventListener('visibilitychange', onVisibilityChange)
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  if (listeners.size === 1) start()
  return () => {
    listeners.delete(listener)
    if (listeners.size === 0) stop()
  }
}

function getSnapshot(): ActionItemsState {
  return state
}

/** Forgets the previous user's items (logout / login): answers already on the way are dropped. */
export function resetActionItemsCache(): void {
  generation += 1
  inflight = null
  lastStartedAt = 0
  consecutiveFailures = 0
  state = INITIAL_STATE
  listeners.forEach((listener) => listener())
}

export function useActionItems(): ActionItemsState & { refresh: () => Promise<void> } {
  const snapshot = useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
  const refresh = useCallback(() => refreshActionItems(), [])
  return { ...snapshot, refresh }
}
