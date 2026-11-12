import type { ReactNode, RefObject } from 'react'
import { Button, Space, Spin, Typography, theme } from 'antd'
import { MobileStateWidget } from './MobileStateWidget'

/** The part of `useInfiniteList` the feed reads; the hook's return value fits as is. */
export type CardFeedSource<T> = {
  items: T[]
  loading: boolean
  loadingMore: boolean
  error: string | null
  hasMore: boolean
  sentinelRef: RefObject<HTMLDivElement | null>
  reload: () => unknown
  loadMore: () => unknown
}

export type MobileCardFeedWidgetProps<T> = {
  list: CardFeedSource<T>
  getKey: (item: T) => string | number
  renderItem: (item: T) => ReactNode
  /** Shown when the first page is empty. */
  empty: ReactNode
  /** Accessible name of the list, e.g. «Заявки». */
  label?: string
}

/**
 * Cursor feed of cards: skeletons on the first load, an empty or error state, then the cards and a sentinel that loads
 * the next page while scrolling («Загружаем ещё…»).
 */
export function MobileCardFeedWidget<T>({ list, getKey, renderItem, empty, label }: MobileCardFeedWidgetProps<T>) {
  const { token } = theme.useToken()
  const { items, loading, loadingMore, error, hasMore, sentinelRef } = list

  if (items.length === 0) {
    if (loading) return <MobileStateWidget state="loading" />
    if (error) return <MobileStateWidget state="error" onRetry={() => void list.reload()} />
    return <>{empty}</>
  }

  return (
    <div>
      <ul aria-label={label} style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 12 }}>
        {items.map((item) => (
          <li key={getKey(item)}>{renderItem(item)}</li>
        ))}
      </ul>
      <div ref={sentinelRef} style={{ padding: '16px 0', textAlign: 'center' }} data-testid="mobile-feed-footer">
        {loadingMore ? (
          <Space size={8} role="status">
            <Spin size="small" />
            <Typography.Text style={{ color: token.colorTextSecondary }}>Загружаем ещё…</Typography.Text>
          </Space>
        ) : error ? (
          <Space direction="vertical" size={8} role="alert">
            <Typography.Text style={{ color: token.colorTextSecondary }}>Не удалось загрузить продолжение</Typography.Text>
            <Button onClick={() => void list.loadMore()}>Повторить</Button>
          </Space>
        ) : hasMore ? (
          <Button type="link" onClick={() => void list.loadMore()}>
            Показать ещё
          </Button>
        ) : null}
      </div>
    </div>
  )
}
