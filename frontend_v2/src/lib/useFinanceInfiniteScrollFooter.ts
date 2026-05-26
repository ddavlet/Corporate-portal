import { useCallback, useEffect, useRef } from 'react'

const SENTINEL_ROOT_MARGIN_PX = 240

export type FinanceInfiniteListSource = {
  hasMore: boolean
  loadingMore: boolean
  loadMore: () => Promise<void>
  itemsLength: number
}

function isSentinelNearViewport(node: HTMLElement): boolean {
  const rect = node.getBoundingClientRect()
  return rect.top <= window.innerHeight + SENTINEL_ROOT_MARGIN_PX
}

/** Shared sentinel + drain for one or two finance lists (expenses, revenues, or both). */
export function useFinanceInfiniteScrollFooter(sources: FinanceInfiniteListSource[]) {
  const sentinelRef = useRef<HTMLDivElement | null>(null)
  const sourcesRef = useRef(sources)
  sourcesRef.current = sources

  const hasMore = sources.some((s) => s.hasMore)
  const loadingMore = sources.some((s) => s.loadingMore)
  const itemsLength = sources.reduce((sum, s) => sum + s.itemsLength, 0)

  const loadMoreAll = useCallback(async () => {
    const active = sourcesRef.current.filter((s) => s.hasMore)
    if (!active.length) return
    await Promise.all(active.map((s) => s.loadMore()))
  }, [])

  const drainIfVisible = useCallback(() => {
    if (!sourcesRef.current.some((s) => s.hasMore)) return
    const node = sentinelRef.current
    if (!node || !isSentinelNearViewport(node)) return
    void loadMoreAll()
  }, [loadMoreAll])

  useEffect(() => {
    const node = sentinelRef.current
    if (!node) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) void loadMoreAll()
      },
      { rootMargin: `${SENTINEL_ROOT_MARGIN_PX}px` },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [loadMoreAll, itemsLength])

  useEffect(() => {
    if (!hasMore || loadingMore) return
    const frame = requestAnimationFrame(() => drainIfVisible())
    return () => cancelAnimationFrame(frame)
  }, [itemsLength, hasMore, loadingMore, drainIfVisible])

  return { sentinelRef, hasMore, loadingMore, loadMoreAll }
}
