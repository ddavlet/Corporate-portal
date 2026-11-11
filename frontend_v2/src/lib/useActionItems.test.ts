import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const getActionItemsMock = vi.fn()
const syncAppBadgeMock = vi.fn()

vi.mock('./actionItemsApi', () => ({
  // The store asks the endpoint of the current portal mode (one company on a subdomain, all on the shared host).
  getActionItemsForPortal: () => getActionItemsMock(),
  actionItemTag: (item: { kind: string; id: number }) => `${item.kind}-${item.id}`,
}))
vi.mock('./appBadge', () => ({ syncAppBadge: (count: number) => syncAppBadgeMock(count) }))

import {
  ACTION_ITEMS_FOCUS_THROTTLE_MS,
  ACTION_ITEMS_MAX_BACKOFF_MS,
  ACTION_ITEMS_POLL_MS,
  actionItemsPollDelay,
  resetActionItemsCache,
  useActionItems,
} from './useActionItems'

const ITEM = (kind: string, id: number) => ({
  kind,
  id,
  approval_id: id * 10,
  step: 1,
  step_type: 'serial',
  title: `Объект ${id}`,
  amount: '100.00',
  currency: 'UZS',
  type_code: '',
  type_label: '',
  created_at: '2026-11-10T10:00:00Z',
  link: `/requests/${id}`,
})

function setVisibility(value: 'visible' | 'hidden') {
  Object.defineProperty(document, 'visibilityState', { configurable: true, value })
}

/** Lets resolved promises and React updates run under fake timers. */
async function flush(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

describe('useActionItems', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    resetActionItemsCache()
    getActionItemsMock.mockReset()
    syncAppBadgeMock.mockReset()
    setVisibility('visible')
  })

  afterEach(() => {
    vi.useRealTimers()
    delete (navigator as unknown as Record<string, unknown>).serviceWorker
  })

  it('loads on mount and exposes the count and items', async () => {
    getActionItemsMock.mockResolvedValue({ count: 2, items: [ITEM('request', 1), ITEM('invest_return', 2)] })
    const { result, unmount } = renderHook(() => useActionItems())
    expect(result.current.loading).toBe(true)
    await flush()
    expect(result.current).toMatchObject({ count: 2, loading: false, error: false })
    expect(result.current.items).toHaveLength(2)
    expect(syncAppBadgeMock).toHaveBeenLastCalledWith(2)
    unmount()
  })

  it('polls every 60 seconds while the tab is visible', async () => {
    getActionItemsMock.mockResolvedValue({ count: 0, items: [] })
    const { unmount } = renderHook(() => useActionItems())
    await flush()
    expect(getActionItemsMock).toHaveBeenCalledTimes(1)
    await flush(ACTION_ITEMS_POLL_MS)
    expect(getActionItemsMock).toHaveBeenCalledTimes(2)
    await flush(ACTION_ITEMS_POLL_MS)
    expect(getActionItemsMock).toHaveBeenCalledTimes(3)
    unmount()
  })

  it('does not poll a hidden tab and refreshes once it is visible again', async () => {
    getActionItemsMock.mockResolvedValue({ count: 0, items: [] })
    const { unmount } = renderHook(() => useActionItems())
    await flush()
    setVisibility('hidden')
    document.dispatchEvent(new Event('visibilitychange'))
    await flush(ACTION_ITEMS_POLL_MS * 3)
    expect(getActionItemsMock).toHaveBeenCalledTimes(1)

    setVisibility('visible')
    document.dispatchEvent(new Event('visibilitychange'))
    await flush()
    expect(getActionItemsMock).toHaveBeenCalledTimes(2)
    unmount()
  })

  it('asks once when focus and visibilitychange fire together, and not right after a refresh', async () => {
    getActionItemsMock.mockResolvedValue({ count: 0, items: [] })
    const { unmount } = renderHook(() => useActionItems())
    await flush()
    window.dispatchEvent(new Event('focus'))
    await flush()
    expect(getActionItemsMock).toHaveBeenCalledTimes(1)

    await flush(ACTION_ITEMS_FOCUS_THROTTLE_MS)
    window.dispatchEvent(new Event('focus'))
    document.dispatchEvent(new Event('visibilitychange'))
    await flush()
    expect(getActionItemsMock).toHaveBeenCalledTimes(2)
    unmount()
  })

  it('refreshes when the window gets focus', async () => {
    getActionItemsMock.mockResolvedValueOnce({ count: 1, items: [ITEM('request', 1)] })
    getActionItemsMock.mockResolvedValueOnce({ count: 0, items: [] })
    const { result, unmount } = renderHook(() => useActionItems())
    await flush()
    expect(result.current.count).toBe(1)
    await flush(ACTION_ITEMS_FOCUS_THROTTLE_MS)
    window.dispatchEvent(new Event('focus'))
    await flush()
    expect(getActionItemsMock).toHaveBeenCalledTimes(2)
    expect(result.current.count).toBe(0)
    expect(syncAppBadgeMock).toHaveBeenLastCalledWith(0)
    unmount()
  })

  it('asks the server once for two components on screen', async () => {
    getActionItemsMock.mockResolvedValue({ count: 3, items: [] })
    const first = renderHook(() => useActionItems())
    const second = renderHook(() => useActionItems())
    await flush()
    expect(getActionItemsMock).toHaveBeenCalledTimes(1)
    expect(first.result.current.count).toBe(3)
    expect(second.result.current.count).toBe(3)
    await flush(ACTION_ITEMS_POLL_MS)
    expect(getActionItemsMock).toHaveBeenCalledTimes(2)
    first.unmount()
    second.unmount()
  })

  it('stops polling after the last component is gone', async () => {
    getActionItemsMock.mockResolvedValue({ count: 0, items: [] })
    const { unmount } = renderHook(() => useActionItems())
    await flush()
    unmount()
    await flush(ACTION_ITEMS_POLL_MS * 2)
    window.dispatchEvent(new Event('focus'))
    await flush()
    expect(getActionItemsMock).toHaveBeenCalledTimes(1)
  })

  it('treats a failed or forbidden request as zero', async () => {
    getActionItemsMock.mockResolvedValueOnce({ count: 2, items: [ITEM('request', 1), ITEM('request', 2)] })
    getActionItemsMock.mockRejectedValueOnce(Object.assign(new Error('Forbidden'), { status: 403 }))
    const { result, unmount } = renderHook(() => useActionItems())
    await flush()
    expect(result.current.count).toBe(2)
    await flush(ACTION_ITEMS_POLL_MS)
    expect(result.current).toMatchObject({ count: 0, items: [], error: true, loading: false })
    expect(syncAppBadgeMock).toHaveBeenLastCalledWith(0)
    unmount()
  })

  it('backs off after consecutive failures and returns to 60 s after a success', async () => {
    getActionItemsMock.mockRejectedValue(new Error('Server error'))
    const { result, unmount } = renderHook(() => useActionItems())
    await flush()
    expect(getActionItemsMock).toHaveBeenCalledTimes(1)

    // 1 failure: next timer request after 2 minutes, not 1.
    await flush(ACTION_ITEMS_POLL_MS)
    expect(getActionItemsMock).toHaveBeenCalledTimes(1)
    await flush(ACTION_ITEMS_POLL_MS)
    expect(getActionItemsMock).toHaveBeenCalledTimes(2)

    // 2 failures: 4 minutes.
    await flush(ACTION_ITEMS_POLL_MS * 3)
    expect(getActionItemsMock).toHaveBeenCalledTimes(2)
    await flush(ACTION_ITEMS_POLL_MS)
    expect(getActionItemsMock).toHaveBeenCalledTimes(3)

    // Focus still asks right away; the success restores the normal rhythm.
    getActionItemsMock.mockResolvedValue({ count: 1, items: [ITEM('request', 1)] })
    await flush(ACTION_ITEMS_FOCUS_THROTTLE_MS)
    window.dispatchEvent(new Event('focus'))
    await flush()
    expect(getActionItemsMock).toHaveBeenCalledTimes(4)
    expect(result.current).toMatchObject({ count: 1, error: false })
    await flush(ACTION_ITEMS_POLL_MS)
    expect(getActionItemsMock).toHaveBeenCalledTimes(5)
    unmount()
  })

  it('caps the backoff at 5 minutes', () => {
    expect(actionItemsPollDelay(0)).toBe(ACTION_ITEMS_POLL_MS)
    expect(actionItemsPollDelay(1)).toBe(ACTION_ITEMS_POLL_MS * 2)
    expect(actionItemsPollDelay(2)).toBe(ACTION_ITEMS_POLL_MS * 4)
    expect(actionItemsPollDelay(10)).toBe(ACTION_ITEMS_MAX_BACKOFF_MS)
  })

  it('tells the service worker the current tags and count', async () => {
    const postMessage = vi.fn()
    Object.defineProperty(navigator, 'serviceWorker', { configurable: true, value: { controller: { postMessage } } })
    getActionItemsMock.mockResolvedValue({ count: 2, items: [ITEM('request', 7), ITEM('project_investment', 3)] })
    const { unmount } = renderHook(() => useActionItems())
    await flush()
    expect(postMessage).toHaveBeenCalledWith({
      type: 'action-items',
      tags: ['request-7', 'project_investment-3'],
      count: 2,
    })
    unmount()
  })

  it('does not tell the service worker anything when the request fails (shown notifications stay)', async () => {
    const postMessage = vi.fn()
    Object.defineProperty(navigator, 'serviceWorker', { configurable: true, value: { controller: { postMessage } } })
    getActionItemsMock.mockRejectedValue(new Error('offline'))
    const { result, unmount } = renderHook(() => useActionItems())
    await flush()
    expect(result.current.error).toBe(true)
    expect(postMessage).not.toHaveBeenCalled()
    unmount()
  })

  it('shows the sum over companies in the count and the icon badge (crit. 19)', async () => {
    const withTenant = (id: number, subdomain: string) => ({ ...ITEM('request', id), tenant: { subdomain, name: subdomain } })
    getActionItemsMock.mockResolvedValue({ count: 3, items: [withTenant(1, 'alpha'), withTenant(2, 'beta'), withTenant(3, 'beta')] })
    const { result, unmount } = renderHook(() => useActionItems())
    await flush()
    expect(result.current.count).toBe(3)
    expect(syncAppBadgeMock).toHaveBeenLastCalledWith(3)
    unmount()
  })

  it('drops an answer that arrives after a reset', async () => {
    let resolve: (value: unknown) => void = () => undefined
    getActionItemsMock.mockReturnValueOnce(new Promise((r) => (resolve = r)))
    const { result, unmount } = renderHook(() => useActionItems())
    act(() => resetActionItemsCache())
    resolve({ count: 5, items: [] })
    await flush()
    expect(result.current.count).toBe(0)
    expect(result.current.loading).toBe(true)
    unmount()
  })
})
