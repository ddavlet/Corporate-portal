import { Button, Spin, Typography } from 'antd'
import type { RefObject } from 'react'

type ListInfiniteScrollFooterProps = {
  sentinelRef: RefObject<HTMLDivElement | null>
  hasMore: boolean
  visibleCount: number
  /** Total rows fetched from API (before client-side filters). */
  loadedCount?: number
  loadingMore?: boolean
  onLoadMore?: () => void
}

export function ListInfiniteScrollFooter({
  sentinelRef,
  hasMore,
  visibleCount,
  loadedCount,
  loadingMore = false,
  onLoadMore,
}: ListInfiniteScrollFooterProps) {
  const loaded = loadedCount ?? visibleCount
  const hiddenByFilter = loaded > visibleCount

  return (
    <div ref={sentinelRef} style={{ padding: '12px 0', textAlign: 'center' }}>
      {hasMore || loadingMore ? (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
          <Spin size="small" />
          {hasMore && onLoadMore ? (
            <Button type="link" size="small" disabled={loadingMore} onClick={() => void onLoadMore()}>
              Загрузить ещё
            </Button>
          ) : null}
        </div>
      ) : (
        <Typography.Text type="secondary">
          {hiddenByFilter
            ? `Показано ${visibleCount} из ${loaded} (остальные скрыты фильтром)`
            : `Показано ${visibleCount}`}
        </Typography.Text>
      )}
    </div>
  )
}
