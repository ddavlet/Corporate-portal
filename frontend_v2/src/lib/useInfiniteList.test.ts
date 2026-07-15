import { describe, expect, it, vi, beforeEach } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { useInfiniteList, useRestoreInfinitePages } from './useInfiniteList'

vi.mock('./api', () => ({
  fetchCursorListPage: vi.fn(),
}))

import { fetchCursorListPage } from './api'

function mockInfiniteScrollDom() {
  vi.stubGlobal(
    'IntersectionObserver',
    class {
      private readonly callback: IntersectionObserverCallback
      constructor(callback: IntersectionObserverCallback) {
        this.callback = callback
      }
      observe() {
        this.callback([{ isIntersecting: true } as IntersectionObserverEntry], this as unknown as IntersectionObserver)
      }
      disconnect() {}
      unobserve() {}
    },
  )
  Element.prototype.getBoundingClientRect = () =>
    ({
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      width: 0,
      height: 0,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    }) as DOMRect
}

describe('useInfiniteList', () => {
  beforeEach(() => {
    vi.mocked(fetchCursorListPage).mockReset()
    mockInfiniteScrollDom()
  })

  it('loads first page and exposes results', async () => {
    vi.mocked(fetchCursorListPage).mockResolvedValueOnce({
      results: [{ id: 1 }],
      next: '/api/items/?cursor=abc',
      previous: null,
    })

    const { result } = renderHook(() =>
      useInfiniteList<{ id: number }>({ url: '/api/items/', pageSize: 50 }),
    )

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.items).toEqual([{ id: 1 }])
    expect(result.current.hasMore).toBe(true)
    expect(fetchCursorListPage).toHaveBeenCalledWith('/api/items/?page_size=50')
  })

  it('chains loadMore while next cursor exists', async () => {
    vi.mocked(fetchCursorListPage)
      .mockResolvedValueOnce({
        results: [{ id: 1 }],
        next: '/api/items/?cursor=page2',
        previous: null,
      })
      .mockResolvedValueOnce({
        results: [{ id: 2 }],
        next: null,
        previous: null,
      })

    const { result } = renderHook(() => {
      const list = useInfiniteList<{ id: number }>({ url: '/api/items/', pageSize: 50 })
      if (list.sentinelRef.current === null) {
        list.sentinelRef.current = document.createElement('div')
      }
      return list
    })

    await waitFor(() => expect(result.current.loading).toBe(false))
    await waitFor(() => expect(result.current.items).toHaveLength(2))
    expect(fetchCursorListPage).toHaveBeenCalledTimes(2)
    expect(result.current.hasMore).toBe(false)
  })

  it('drops rows re-emitted across cursor pages (no duplicate ids)', async () => {
    // Cursor keyed on a non-unique field (e.g. doc_date) can hand back a row
    // that already appeared on the previous page. The accumulated list must
    // still contain each id exactly once.
    vi.mocked(fetchCursorListPage)
      .mockResolvedValueOnce({
        results: [{ id: 3933 }, { id: 3924 }],
        next: '/api/items/?cursor=page2',
        previous: null,
      })
      .mockResolvedValueOnce({
        results: [{ id: 3924 }, { id: 3910 }],
        next: null,
        previous: null,
      })

    const { result } = renderHook(() => {
      const list = useInfiniteList<{ id: number }>({ url: '/api/items/', pageSize: 50 })
      if (list.sentinelRef.current === null) {
        list.sentinelRef.current = document.createElement('div')
      }
      return list
    })

    await waitFor(() => expect(result.current.loading).toBe(false))
    await waitFor(() => expect(result.current.hasMore).toBe(false))

    expect(result.current.items).toEqual([{ id: 3933 }, { id: 3924 }, { id: 3910 }])
    const ids = result.current.items.map((r) => r.id)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('resets when url changes', async () => {
    vi.mocked(fetchCursorListPage)
      .mockResolvedValueOnce({ results: [{ id: 1 }], next: null, previous: null })
      .mockResolvedValueOnce({ results: [{ id: 2 }], next: null, previous: null })

    const { result, rerender } = renderHook(
      ({ url }) => useInfiniteList<{ id: number }>({ url }),
      { initialProps: { url: '/api/items/?status=A' } },
    )
    await waitFor(() => expect(result.current.items).toEqual([{ id: 1 }]))

    rerender({ url: '/api/items/?status=B' })
    await waitFor(() => expect(result.current.items).toEqual([{ id: 2 }]))
    expect(fetchCursorListPage).toHaveBeenLastCalledWith('/api/items/?status=B&page_size=50')
  })

  it('does not fetch when enabled is false', () => {
    renderHook(() => useInfiniteList<{ id: number }>({ url: '/api/items/', enabled: false }))
    expect(fetchCursorListPage).not.toHaveBeenCalled()
  })

  it('fetches when enabled changes from false to true', async () => {
    vi.mocked(fetchCursorListPage).mockResolvedValueOnce({
      results: [{ id: 1 }],
      next: null,
      previous: null,
    })

    const { result, rerender } = renderHook(
      ({ enabled }) => useInfiniteList<{ id: number }>({ url: '/api/items/', enabled }),
      { initialProps: { enabled: false } },
    )

    expect(fetchCursorListPage).not.toHaveBeenCalled()

    rerender({ enabled: true })
    await waitFor(() => expect(result.current.items).toEqual([{ id: 1 }]))
    expect(fetchCursorListPage).toHaveBeenCalledTimes(1)
  })

  it('discards stale loadFirstPage response when URL changes mid-fetch', async () => {
    let resolveFirst!: (val: { results: { id: number }[]; next: string | null; previous: null }) => void
    const firstRequest = new Promise<{ results: { id: number }[]; next: string | null; previous: null }>(
      (r) => { resolveFirst = r },
    )

    vi.mocked(fetchCursorListPage)
      .mockReturnValueOnce(firstRequest as never)
      .mockResolvedValueOnce({ results: [{ id: 2 }], next: null, previous: null })

    const { result, rerender } = renderHook(
      ({ url }) => useInfiniteList<{ id: number }>({ url }),
      { initialProps: { url: '/api/items/?v=1' } },
    )

    // First fetch in-flight; immediately change URL to increment epoch
    rerender({ url: '/api/items/?v=2' })

    // Wait for fresh second fetch to settle
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.items).toEqual([{ id: 2 }])

    // Resolve stale first response after epoch has advanced
    await act(async () => {
      resolveFirst({ results: [{ id: 1 }], next: '/api/items/?cursor=stale', previous: null })
    })

    expect(result.current.items).toEqual([{ id: 2 }])
    expect(result.current.hasMore).toBe(false)
  })

  it('discards stale loadMore response when URL changes mid-loadMore', async () => {
    let resolveMore!: (val: { results: { id: number }[]; next: string | null; previous: null }) => void
    const moreRequest = new Promise<{ results: { id: number }[]; next: string | null; previous: null }>(
      (r) => { resolveMore = r },
    )

    vi.mocked(fetchCursorListPage)
      .mockResolvedValueOnce({ results: [{ id: 1 }], next: '/api/items/?cursor=page2', previous: null })
      .mockReturnValueOnce(moreRequest as never)
      .mockResolvedValueOnce({ results: [{ id: 3 }], next: null, previous: null })

    const { result, rerender } = renderHook(
      ({ url }) => useInfiniteList<{ id: number }>({ url }),
      { initialProps: { url: '/api/items/' } },
    )

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.items).toEqual([{ id: 1 }])

    // Manually start loadMore — it suspends on moreRequest
    void result.current.loadMore()
    await waitFor(() => expect(result.current.loadingMore).toBe(true))

    // URL changes → new epoch, loadFirstPage for v=2 starts and resolves
    rerender({ url: '/api/items/?v=2' })
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.items).toEqual([{ id: 3 }])

    // Resolve the stale loadMore — must not append {id:2} to the new list
    await act(async () => {
      resolveMore({ results: [{ id: 2 }], next: null, previous: null })
    })

    expect(result.current.items).toEqual([{ id: 3 }])
  })
})

describe('useRestoreInfinitePages', () => {
  it('does not call loadMore while hasMore is false', () => {
    const loadMore = vi.fn().mockResolvedValue(undefined)

    renderHook(() =>
      useRestoreInfinitePages({ targetPages: 3, hasMore: false, loading: false, loadMore }),
    )

    expect(loadMore).not.toHaveBeenCalled()
  })

  it('calls loadMore targetPages-1 times once hasMore becomes true', async () => {
    const loadMore = vi.fn().mockResolvedValue(undefined)

    const { rerender } = renderHook(
      ({ hasMore }: { hasMore: boolean }) =>
        useRestoreInfinitePages({ targetPages: 3, hasMore, loading: false, loadMore }),
      { initialProps: { hasMore: false } },
    )

    expect(loadMore).not.toHaveBeenCalled()

    rerender({ hasMore: true })
    await waitFor(() => expect(loadMore).toHaveBeenCalledTimes(2))
  })

  it('skips restore when targetPages is 1', () => {
    const loadMore = vi.fn().mockResolvedValue(undefined)

    renderHook(() =>
      useRestoreInfinitePages({ targetPages: 1, hasMore: true, loading: false, loadMore }),
    )

    expect(loadMore).not.toHaveBeenCalled()
  })

  it('does not re-fire after completing restore', async () => {
    const loadMore = vi.fn().mockResolvedValue(undefined)

    const { rerender } = renderHook(
      ({ loading }: { loading: boolean }) =>
        useRestoreInfinitePages({ targetPages: 2, hasMore: true, loading, loadMore }),
      { initialProps: { loading: false } },
    )

    await waitFor(() => expect(loadMore).toHaveBeenCalledTimes(1))

    // Simulate state updates that re-run the effect — loadMore must not fire again
    rerender({ loading: false })
    await act(async () => {})

    expect(loadMore).toHaveBeenCalledTimes(1)
  })
})
