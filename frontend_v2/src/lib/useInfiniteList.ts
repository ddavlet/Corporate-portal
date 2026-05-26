import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchCursorListPage } from './api'

export type UseInfiniteListOptions = {
  /** Relative API path with optional query string, e.g. `/api/requests/?status=PAYED` */
  url: string
  enabled?: boolean
  pageSize?: number
}

const SENTINEL_ROOT_MARGIN_PX = 240

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

function isSentinelNearViewport(node: HTMLElement): boolean {
  const rect = node.getBoundingClientRect()
  return rect.top <= window.innerHeight + SENTINEL_ROOT_MARGIN_PX
}

export function useInfiniteList<T>({ url, enabled = true, pageSize = 50 }: UseInfiniteListOptions) {
  const [items, setItems] = useState<T[]>([])
  const [next, setNext] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const sentinelRef = useRef<HTMLDivElement | null>(null)
  const nextRef = useRef<string | null>(null)
  const loadingRef = useRef(false)
  const loadingMoreRef = useRef(false)
  const enabledRef = useRef(enabled)

  useEffect(() => {
    nextRef.current = next
  }, [next])

  useEffect(() => {
    loadingRef.current = loading
  }, [loading])

  useEffect(() => {
    loadingMoreRef.current = loadingMore
  }, [loadingMore])

  useEffect(() => {
    enabledRef.current = enabled
  }, [enabled])

  const drainIfSentinelVisibleRef = useRef<() => void>(() => {})

  const loadMore = useCallback(async () => {
    const nextUrl = nextRef.current
    if (!nextUrl || loadingMoreRef.current || loadingRef.current) return
    loadingMoreRef.current = true
    setLoadingMore(true)
    try {
      const page = await fetchCursorListPage<T>(resolveApiUrl(nextUrl))
      setItems((prev) => [...prev, ...page.results])
      setNext(page.next)
      nextRef.current = page.next
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Ошибка запроса')
    } finally {
      loadingMoreRef.current = false
      setLoadingMore(false)
      requestAnimationFrame(() => drainIfSentinelVisibleRef.current())
    }
  }, [])

  drainIfSentinelVisibleRef.current = () => {
    if (!enabledRef.current || loadingRef.current || loadingMoreRef.current || !nextRef.current) return
    const node = sentinelRef.current
    if (!node || !isSentinelNearViewport(node)) return
    void loadMore()
  }

  const loadFirstPage = useCallback(async () => {
    if (!enabled) return
    setLoading(true)
    setError(null)
    try {
      const page = await fetchCursorListPage<T>(withPageSize(url, pageSize))
      setItems(page.results)
      setNext(page.next)
      nextRef.current = page.next
    } catch (e: unknown) {
      setItems([])
      setNext(null)
      nextRef.current = null
      setError(e instanceof Error ? e.message : 'Ошибка запроса')
    } finally {
      setLoading(false)
      requestAnimationFrame(() => drainIfSentinelVisibleRef.current())
    }
  }, [url, enabled, pageSize])

  useEffect(() => {
    void loadFirstPage()
  }, [loadFirstPage])

  useEffect(() => {
    const node = sentinelRef.current
    if (!node || !enabled) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) void loadMore()
      },
      { rootMargin: `${SENTINEL_ROOT_MARGIN_PX}px` },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [loadMore, enabled, items.length])

  /** IntersectionObserver does not re-fire when the sentinel stays visible after append — drain while in view. */
  useEffect(() => {
    if (!enabled || loading || loadingMore || !next) return
    const frame = requestAnimationFrame(() => drainIfSentinelVisibleRef.current())
    return () => cancelAnimationFrame(frame)
  }, [items.length, loading, loadingMore, next, enabled])

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
    /** Call when sentinel mounts or tab becomes visible (e.g. after switching Ant Design Tabs). */
    resumeLoading: () => drainIfSentinelVisibleRef.current(),
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
