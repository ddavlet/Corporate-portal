import { useCallback, useEffect, useLayoutEffect, useRef } from 'react'

export type ListPageSessionSnapshot = {
  scrollY: number
  visibleCount?: number
  selectedRowId?: number | string | null
  [key: string]: unknown
}

type UseListPageSessionOptions<T extends ListPageSessionSnapshot> = {
  /** sessionStorage key, e.g. `list-session:/requests` */
  storageKey: string
  enabled?: boolean
  /** Called once on mount when saved snapshot exists (before paint when possible). */
  onRestore?: (snapshot: T) => void
  /** Build snapshot to persist; scrollY is added automatically. */
  getSnapshot: () => Omit<T, 'scrollY'> | T
  /** Restore scroll after list content is ready (e.g. loading finished). */
  ready?: boolean
}

function readSnapshot<T extends ListPageSessionSnapshot>(key: string): T | null {
  try {
    const raw = sessionStorage.getItem(key)
    if (!raw) return null
    const parsed = JSON.parse(raw) as T
    if (!parsed || typeof parsed !== 'object') return null
    return parsed
  } catch {
    return null
  }
}

/**
 * Persists list UI state in sessionStorage so browser back / return navigation
 * restores filters slice, scroll, and selection like a feed.
 */
export function useListPageSession<T extends ListPageSessionSnapshot>({
  storageKey,
  enabled = true,
  onRestore,
  getSnapshot,
  ready = true,
}: UseListPageSessionOptions<T>) {
  const restoredRef = useRef(false)
  const scrollRestoredRef = useRef(false)
  const getSnapshotRef = useRef(getSnapshot)
  const onRestoreRef = useRef(onRestore)

  useEffect(() => {
    getSnapshotRef.current = getSnapshot
  }, [getSnapshot])

  useEffect(() => {
    onRestoreRef.current = onRestore
  }, [onRestore])

  useEffect(() => {
    if (!enabled || restoredRef.current) return
    const saved = readSnapshot<T>(storageKey)
    if (saved) onRestoreRef.current?.(saved)
    restoredRef.current = true
  }, [enabled, storageKey])

  const persist = useCallback(() => {
    if (!enabled) return
    try {
      const base = getSnapshotRef.current() as T
      const payload = {
        ...base,
        scrollY: window.scrollY,
      } as T
      sessionStorage.setItem(storageKey, JSON.stringify(payload))
    } catch {
      // ignore quota / private mode
    }
  }, [enabled, storageKey])

  useEffect(() => {
    if (!enabled) return
    const onPageHide = () => persist()
    window.addEventListener('pagehide', onPageHide)
    return () => {
      window.removeEventListener('pagehide', onPageHide)
      persist()
    }
  }, [enabled, persist])

  useLayoutEffect(() => {
    if (!enabled || !ready || !restoredRef.current || scrollRestoredRef.current) return
    const saved = readSnapshot<T>(storageKey)
    if (!saved || typeof saved.scrollY !== 'number' || saved.scrollY <= 0) return
    window.scrollTo({ top: saved.scrollY, behavior: 'auto' })
    scrollRestoredRef.current = true
  }, [enabled, ready, storageKey])

  return { persist }
}
