import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Button, Drawer, Input, Typography, theme } from 'antd'
import { ArrowLeftOutlined, CheckOutlined, PlusOutlined, SearchOutlined } from '@ant-design/icons'
import { MobileStateWidget } from './MobileStateWidget'

/** Directory lookups of the pickers ask for up to this many rows per search (`page_size=200&search=…`). */
export const PICKER_PAGE_SIZE = 200
export const PICKER_SEARCH_DEBOUNCE_MS = 300

export type MobilePickerSheetProps<T> = {
  open: boolean
  title: string
  onClose: () => void
  /** Loads the rows for a search string (empty: the first rows); build the request with PICKER_PAGE_SIZE. */
  load: (search: string) => Promise<T[]>
  getKey: (item: T) => string | number
  renderItem: (item: T) => ReactNode
  onSelect: (item: T) => void
  selectedKey?: string | number | null
  searchPlaceholder?: string
  /** «Новый поставщик» and the like: shown above the rows, gets the current search text. */
  createLabel?: string
  onCreate?: (search: string) => void
  emptyText?: string
}

type LoadState<T> = { status: 'loading' } | { status: 'error' } | { status: 'ready'; items: T[] }

/**
 * Full-screen directory picker of the mobile layout: a search field (debounced), the matching rows and an optional
 * «Новый …» action. Picking a row calls onSelect; the caller closes the picker and keeps its own form as it was.
 */
export function MobilePickerSheet<T>({
  open,
  title,
  onClose,
  load,
  getKey,
  renderItem,
  onSelect,
  selectedKey,
  searchPlaceholder = 'Поиск',
  createLabel,
  onCreate,
  emptyText = 'Ничего не найдено',
}: MobilePickerSheetProps<T>) {
  const { token } = theme.useToken()
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [state, setState] = useState<LoadState<T>>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)
  const requestRef = useRef(0)
  const loadRef = useRef(load)

  useEffect(() => {
    loadRef.current = load
  }, [load])

  // A fresh picker every time it opens: the search is cleared when it closes.
  useEffect(() => {
    if (open) return
    setSearch('')
    setQuery('')
  }, [open])

  useEffect(() => {
    if (!open) return
    const timer = setTimeout(() => setQuery(search.trim()), PICKER_SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [search, open])

  useEffect(() => {
    if (!open) return
    const request = ++requestRef.current
    setState({ status: 'loading' })
    loadRef
      .current(query)
      .then((items) => {
        if (request === requestRef.current) setState({ status: 'ready', items })
      })
      .catch(() => {
        if (request === requestRef.current) setState({ status: 'error' })
      })
  }, [open, query, attempt])

  const retry = useCallback(() => setAttempt((n) => n + 1), [])

  return (
    <Drawer
      open={open}
      onClose={onClose}
      placement="right"
      width="100%"
      rootClassName="m-picker"
      closable={false}
      destroyOnHidden
      title={
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <Button
            type="text"
            className="m-header__button"
            icon={<ArrowLeftOutlined />}
            aria-label="Назад"
            onClick={onClose}
          />
          <Typography.Text strong className="m-ellipsis" style={{ fontSize: 17 }}>
            {title}
          </Typography.Text>
        </div>
      }
    >
      <div style={{ padding: '12px 16px', position: 'sticky', top: 0, zIndex: 1, background: token.colorBgElevated }}>
        <Input
          autoFocus
          allowClear
          prefix={<SearchOutlined aria-hidden />}
          placeholder={searchPlaceholder}
          aria-label={searchPlaceholder}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          enterKeyHint="search"
        />
      </div>

      {onCreate && createLabel ? (
        <button
          type="button"
          className="m-list-row"
          onClick={() => onCreate(search.trim())}
          style={{ color: token.colorPrimary, borderBottom: `1px solid ${token.colorBorderSecondary}` }}
        >
          <PlusOutlined aria-hidden />
          <span>{createLabel}</span>
        </button>
      ) : null}

      {state.status === 'loading' ? (
        <div style={{ padding: 16 }}>
          <MobileStateWidget state="loading" rows={4} />
        </div>
      ) : state.status === 'error' ? (
        <MobileStateWidget state="error" onRetry={retry} />
      ) : state.items.length === 0 ? (
        <MobileStateWidget state="empty" title={emptyText} />
      ) : (
        <ul aria-label={title} style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {state.items.map((item) => {
            const key = getKey(item)
            const selected = selectedKey !== undefined && selectedKey !== null && key === selectedKey
            return (
              <li key={key} style={{ borderBottom: `1px solid ${token.colorBorderSecondary}` }}>
                <button
                  type="button"
                  className="m-list-row"
                  aria-pressed={selected}
                  onClick={() => onSelect(item)}
                >
                  <span style={{ flex: 1, minWidth: 0, overflowWrap: 'anywhere' }}>{renderItem(item)}</span>
                  {selected ? <CheckOutlined aria-hidden style={{ color: token.colorPrimary }} /> : null}
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </Drawer>
  )
}
