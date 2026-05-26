import { describe, expect, it, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useInfiniteList } from './useInfiniteList'

vi.mock('./api', () => ({
  fetchCursorListPage: vi.fn(),
}))

import { fetchCursorListPage } from './api'

describe('useInfiniteList', () => {
  beforeEach(() => {
    vi.mocked(fetchCursorListPage).mockReset()
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
