import { describe, expect, it, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useInfiniteList } from './useInfiniteList'

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
})
