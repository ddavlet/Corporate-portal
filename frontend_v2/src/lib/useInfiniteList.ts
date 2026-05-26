import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchCursorListPage } from './api'

export type UseInfiniteListOptions = {
  /** Relative API path with optional query string, e.g. `/api/requests/?status=PAYED` */
  url: string
  enabled?: boolean
  pageSize?: number
}

function withPageSize(url: string, pageSize: number): string {
  if (url.includes('page_size=')) return url
  const sep = url.includes('?') ? '&' : '?'
  return `${url}${sep}page_size=${pageSize}`
}

function resolveApiUrl(pathOrUrl: string): string {
  if (pathOrUrl.startsWith('http://') || pathOrUrl.startsWith('https://')) {
    try {
      const u = new URL(pathOrUrl)
      return `${u.pathname}${u.search}`
    } catch {
      return pathOrUrl
    }
  }
  return pathOrUrl
}

export function useInfiniteList<T>({ url, enabled = true, pageSize = 50 }: UseInfiniteListOptions) {
  const [items, setItems] = useState<T[]>([])
  const [next, setNext] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const sentinelRef = useRef<HTMLDivElement | null>(null)

  const loadFirstPage = useCallback(async () => {
    if (!enabled) return
    setLoading(true)
    setError(null)
    try {
      const page = await fetchCursorListPage<T>(withPageSize(url, pageSize))
      setItems(page.results)
      setNext(page.next)
    } catch (e: unknown) {
      setItems([])
      setNext(null)
      setError(e instanceof Error ? e.message : 'Ошибка запроса')
    } finally {
      setLoading(false)
    }
  }, [url, enabled, pageSize])

  useEffect(() => {
    void loadFirstPage()
  }, [loadFirstPage])

  const loadMore = useCallback(async () => {
    if (!next || loadingMore || loading) return
    setLoadingMore(true)
    try {
      const page = await fetchCursorListPage<T>(resolveApiUrl(next))
      setItems((prev) => [...prev, ...page.results])
      setNext(page.next)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Ошибка запроса')
    } finally {
      setLoadingMore(false)
    }
  }, [next, loadingMore, loading])

  useEffect(() => {
    const node = sentinelRef.current
    if (!node || !enabled) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) void loadMore()
      },
      { rootMargin: '240px' },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [loadMore, enabled])

  const pagesLoaded = Math.max(1, Math.ceil(items.length / pageSize))

  return {
    items,
    setItems,
    next,
    loading,
    loadingMore,
    error,
    hasMore: Boolean(next),
    loadMore,
    reload: loadFirstPage,
    sentinelRef,
    pagesLoaded,
  }
}

/** After session restore, prefetch additional cursor pages that were open before navigation. */
export function useRestoreInfinitePages({
  targetPages,
  hasMore,
  loading,
  loadMore,
}: {
  targetPages?: number
  hasMore: boolean
  loading: boolean
  loadMore: () => Promise<void>
}) {
  const doneRef = useRef(false)

  useEffect(() => {
    doneRef.current = false
  }, [targetPages])

  useEffect(() => {
    if (doneRef.current || loading || !targetPages || targetPages <= 1) {
      if (!loading) doneRef.current = true
      return
    }
    let cancelled = false
    ;(async () => {
      let pages = 1
      while (pages < targetPages && hasMore && !cancelled) {
        await loadMore()
        pages += 1
      }
      if (!cancelled) doneRef.current = true
    })()
    return () => {
      cancelled = true
    }
  }, [targetPages, hasMore, loading, loadMore])
}
