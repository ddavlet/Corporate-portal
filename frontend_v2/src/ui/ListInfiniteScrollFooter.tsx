import { Spin, Typography } from 'antd'
import type { RefObject } from 'react'

type ListInfiniteScrollFooterProps = {
  sentinelRef: RefObject<HTMLDivElement | null>
  hasMore: boolean
  visibleCount: number
  loadingMore?: boolean
}

export function ListInfiniteScrollFooter({
  sentinelRef,
  hasMore,
  visibleCount,
  loadingMore = false,
}: ListInfiniteScrollFooterProps) {
  return (
    <div ref={sentinelRef} style={{ padding: '12px 0', textAlign: 'center' }}>
      {hasMore || loadingMore ? (
        <Spin size="small" />
      ) : (
        <Typography.Text type="secondary">Показано {visibleCount}</Typography.Text>
      )}
    </div>
  )
}
