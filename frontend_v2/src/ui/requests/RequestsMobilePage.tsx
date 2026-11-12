import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Badge, Button, Input, Spin, theme } from 'antd'
import { CloseOutlined, FilterOutlined, PlusOutlined, RightOutlined, SearchOutlined } from '@ant-design/icons'
import type { ActionItem } from '../../lib/actionItemsApi'
import { useActionItems } from '../../lib/useActionItems'
import { useInfiniteList, useRestoreInfinitePages } from '../../lib/useInfiniteList'
import { useListPageSession } from '../../lib/useListPageSession'
import { formatRequestDate } from '../../lib/requestUtils'
import { useCompany } from '../company'
import { useMobileHeader, useMobileShell } from '../mobileShell'
import { MobileCardFeedWidget } from '../MobileCardFeedWidget'
import { MobileStateWidget } from '../MobileStateWidget'
import {
  DEFAULT_REQUESTS_TAB,
  EMPTY_MOBILE_FILTERS,
  activeFilterChips,
  buildRequestsListUrl,
  clearFilters,
  normalizeMobileFilters,
  parseRequestsTab,
  removeFilterChip,
  type MobileRequestsFilters,
  type RequestsTab,
} from './requestsListQuery'
import {
  RequestMobileCardBody,
  RequestMobileCardFrame,
  RequestMobileCardWidget,
  RequestStatusToneTag,
  formatRequestAmount,
  type RequestFeedRow,
} from './RequestMobileCardWidget'
import { RequestsFilterSheet } from './RequestsFilterSheet'

/** Separate from the desktop list's `list-session:/requests`; cleared with the other list sessions on a company switch. */
export const REQUESTS_MOBILE_SESSION_KEY = 'list-session:/requests:mobile'
const SEARCH_DEBOUNCE_MS = 300

type MobileRequestsSession = {
  scrollY: number
  tab?: RequestsTab
  filters?: MobileRequestsFilters
  pagesLoaded?: number
}

type SavedSession = { tab: RequestsTab | null; filters: MobileRequestsFilters; pagesLoaded: number }

function readSavedSession(): SavedSession | null {
  try {
    const raw = sessionStorage.getItem(REQUESTS_MOBILE_SESSION_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<MobileRequestsSession> | null
    if (!parsed || typeof parsed !== 'object') return null
    return {
      tab: parseRequestsTab(parsed.tab),
      filters: normalizeMobileFilters(parsed.filters),
      pagesLoaded: typeof parsed.pagesLoaded === 'number' && parsed.pagesLoaded > 1 ? Math.floor(parsed.pagesLoaded) : 1,
    }
  } catch {
    return null
  }
}

/** Tab and filters of the feed: restoring the session applies only while they stay as they were on mount. */
function listQueryKey(tab: RequestsTab, filters: MobileRequestsFilters): string {
  return JSON.stringify([tab, filters])
}

const TAB_LABELS: Record<RequestsTab, string> = {
  waiting: 'Ждут меня',
  all: 'Все',
  my: 'Мои',
  drafts: 'Черновики',
}

/**
 * Requests on a phone: «Ждут меня» (the action items of the current company), «Все», «Мои» and «Черновики» as a cursor
 * feed of cards with search, a filter sheet and chips. Coming back from a card restores the tab, the filters, the loaded
 * pages and the scroll.
 */
export function RequestsMobilePage() {
  const { token } = theme.useToken()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { userId, userIdStatus, openCompanySwitcher } = useMobileShell()
  const [saved] = useState(readSavedSession)

  const urlTab = parseRequestsTab(searchParams.get('tab'))
  const tab: RequestsTab = urlTab ?? saved?.tab ?? DEFAULT_REQUESTS_TAB

  const [filters, setFilters] = useState<MobileRequestsFilters>(() => saved?.filters ?? EMPTY_MOBILE_FILTERS)
  const [searchText, setSearchText] = useState(() => saved?.filters.search ?? '')
  const [filterOpen, setFilterOpen] = useState(false)
  // «Назад» from a card loads the pages again and scrolls back, only on the tab the feed was left on and only until the
  // tab or the filters change: after that the pages and the scroll belong to another list.
  const [restore, setRestore] = useState(() => ({
    key: listQueryKey(tab, filters),
    pages: saved && saved.pagesLoaded > 1 && saved.tab === tab ? saved.pagesLoaded : undefined,
    scroll: saved?.tab === tab,
  }))
  const queryKey = listQueryKey(tab, filters)
  if ((restore.pages !== undefined || restore.scroll) && queryKey !== restore.key) {
    setRestore({ key: restore.key, pages: undefined, scroll: false })
  }
  const restorePages = queryKey === restore.key ? restore.pages : undefined
  const restoreScroll = queryKey === restore.key && restore.scroll

  const selectTab = useCallback(
    (next: RequestsTab) => {
      setSearchParams(
        (prev) => {
          const params = new URLSearchParams(prev)
          params.set('tab', next)
          return params
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  // The address always names the tab, so «Назад» from a card returns to it.
  useEffect(() => {
    if (!urlTab) selectTab(tab)
  }, [urlTab, tab, selectTab])

  // «Мои» needs the user's id: without it the tab is hidden and its address falls back to «Все».
  useEffect(() => {
    if (tab === 'my' && userIdStatus === 'missing') selectTab('all')
  }, [tab, userIdStatus, selectTab])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setFilters((prev) => (prev.search === searchText ? prev : { ...prev, search: searchText }))
    }, SEARCH_DEBOUNCE_MS)
    return () => window.clearTimeout(timer)
  }, [searchText])

  const listUrl = buildRequestsListUrl(tab, filters, userId)
  const list = useInfiniteList<RequestFeedRow>({ url: listUrl ?? '/api/requests/', enabled: listUrl !== null })
  useRestoreInfinitePages({ targetPages: restorePages, hasMore: list.hasMore, loading: list.loading, loadMore: list.loadMore })

  // The list starts loading in an effect: until its first answer an empty list means «not asked yet», not «no requests».
  // Only an empty list waits for it: rows must reach the feed in the same render as they arrive, so the scroll sentinel
  // mounts while `useInfiniteList` still looks for it.
  const [firstAnswer, setFirstAnswer] = useState(false)
  const wasLoadingRef = useRef(false)
  useEffect(() => {
    if (list.loading) wasLoadingRef.current = true
    else if (wasLoadingRef.current) setFirstAnswer(true)
  }, [list.loading])
  // A new tab or new filters keep the previous cards (dimmed) until the answer: the feed's scroll sentinel stays
  // mounted, so loading on scroll keeps working when the new list has as many rows as the old one.
  const refreshing = list.loading && list.items.length > 0

  const actionItems = useActionItems()
  const waiting = useWaitingItems(actionItems.items)

  const listReady =
    listUrl !== null &&
    !list.loading &&
    !list.error &&
    (!restorePages || list.pagesLoaded >= restorePages || !list.hasMore)
  useListPageSession<MobileRequestsSession>({
    storageKey: REQUESTS_MOBILE_SESSION_KEY,
    ready: restoreScroll && (tab === 'waiting' ? !actionItems.loading : listReady),
    getSnapshot: () => ({
      tab,
      filters: { ...filters, search: searchText },
      pagesLoaded: tab === 'waiting' ? 1 : list.pagesLoaded,
    }),
  })

  const headerAction = useMemo(
    () => (
      <Button
        type="text"
        className="m-header__button"
        icon={<PlusOutlined />}
        aria-label="Новая заявка"
        onClick={() => navigate('/requests/new')}
      />
    ),
    [navigate],
  )
  useMobileHeader({ title: 'Заявки', action: headerAction })

  const chips = activeFilterChips(filters, tab)
  const hasQuery = chips.length > 0 || filters.search.trim() !== ''

  const resetAll = () => {
    setSearchText('')
    setFilters(clearFilters(filters))
  }

  return (
    <div style={{ display: 'grid', gap: 12, minWidth: 0 }}>
      <TabsRow
        tab={tab}
        onSelect={selectTab}
        waitingCount={actionItems.loading || actionItems.error ? null : waiting.current.length}
        myState={userIdStatus}
      />

      {tab === 'waiting' ? (
        <WaitingTab
          state={actionItems}
          waiting={waiting}
          onRetry={() => void actionItems.refresh()}
          onShowAll={() => selectTab('all')}
          onOpenOtherCompanies={openCompanySwitcher}
        />
      ) : (
        <>
          <div style={{ display: 'flex', gap: 8, minWidth: 0 }}>
            <Input
              allowClear
              prefix={<SearchOutlined aria-hidden />}
              placeholder="Поиск по заявкам"
              aria-label="Поиск по заявкам"
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              enterKeyHint="search"
              style={{ flex: 1, minWidth: 0 }}
            />
            <Badge count={chips.length} size="small">
              <Button
                icon={<FilterOutlined />}
                aria-label={chips.length > 0 ? `Фильтры, выбрано: ${chips.length}` : 'Фильтры'}
                aria-haspopup="dialog"
                onClick={() => setFilterOpen(true)}
                style={{ width: 44, flexShrink: 0 }}
              />
            </Badge>
          </div>

          {chips.length > 0 ? (
            <ul aria-label="Выбранные фильтры" style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {chips.map((chip) => (
                <li key={chip.key} style={{ minWidth: 0, maxWidth: '100%' }}>
                  <Button
                    shape="round"
                    icon={<CloseOutlined aria-hidden />}
                    iconPosition="end"
                    aria-label={`Убрать фильтр: ${chip.label}`}
                    onClick={() => setFilters(removeFilterChip(filters, chip.key))}
                    style={{ maxWidth: '100%' }}
                  >
                    <span className="m-ellipsis">{chip.label}</span>
                  </Button>
                </li>
              ))}
            </ul>
          ) : null}

          {refreshing ? (
            <div role="status" style={{ display: 'flex', alignItems: 'center', gap: 8, color: token.colorTextSecondary }}>
              <Spin size="small" />
              <span>Обновляем…</span>
            </div>
          ) : null}

          {(tab === 'my' && userIdStatus !== 'ready') || (!firstAnswer && list.items.length === 0 && !list.error) ? (
            <MobileStateWidget state="loading" />
          ) : (
            <div aria-busy={refreshing} style={{ opacity: refreshing ? 0.5 : 1, minWidth: 0 }}>
              <MobileCardFeedWidget<RequestFeedRow>
                list={list}
                label="Заявки"
                getKey={(row) => row.id}
                renderItem={(row) => <RequestMobileCardWidget request={row} />}
                empty={
                  hasQuery ? (
                    <MobileStateWidget
                      state="empty"
                      title="Ничего не найдено"
                      description="Измените поиск или фильтры."
                      action={<Button onClick={resetAll}>Сбросить фильтры</Button>}
                    />
                  ) : tab === 'all' ? (
                    <MobileStateWidget
                      state="empty"
                      title="Заявок пока нет"
                      action={
                        <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/requests/new')}>
                          Новая заявка
                        </Button>
                      }
                    />
                  ) : (
                    <MobileStateWidget
                      state="empty"
                      title={tab === 'my' ? 'У вас нет заявок' : 'Черновиков нет'}
                      action={<Button onClick={() => selectTab('all')}>Показать все заявки</Button>}
                    />
                  )
                }
              />
            </div>
          )}

          <RequestsFilterSheet
            open={filterOpen}
            tab={tab}
            value={filters}
            onClose={() => setFilterOpen(false)}
            onApply={(next) => {
              setFilters({ ...next, search: filters.search })
              setFilterOpen(false)
            }}
          />
        </>
      )}
    </div>
  )
}

/** Request items of the action items: those of the current company, and how many wait in the other companies. */
function useWaitingItems(items: ActionItem[]): { current: ActionItem[]; otherCompanies: number } {
  const { enabled: companyMode, current } = useCompany()
  return useMemo(() => {
    const requests = items.filter((item) => item.kind === 'request')
    // On the shared app host the items cover every company of the user; the feed shows the current one only.
    const mine = companyMode ? requests.filter((item) => item.tenant?.subdomain === current) : requests
    return { current: mine, otherCompanies: requests.length - mine.length }
  }, [items, companyMode, current])
}

type TabsRowProps = {
  tab: RequestsTab
  onSelect: (tab: RequestsTab) => void
  /** Shown as «Ждут меня (N)» once the action items have answered. */
  waitingCount: number | null
  myState: 'loading' | 'ready' | 'missing'
}

function TabsRow({ tab, onSelect, waitingCount, myState }: TabsRowProps) {
  const tabs: RequestsTab[] = myState === 'missing' ? ['waiting', 'all', 'drafts'] : ['waiting', 'all', 'my', 'drafts']
  return (
    <div
      role="group"
      aria-label="Вкладки заявок"
      style={{ display: 'flex', gap: 8, overflowX: 'auto', scrollbarWidth: 'none', minWidth: 0, paddingBottom: 2 }}
    >
      {tabs.map((key) => {
        const label = key === 'waiting' && waitingCount !== null ? `${TAB_LABELS.waiting} (${waitingCount})` : TAB_LABELS[key]
        const active = key === tab
        return (
          <Button
            key={key}
            shape="round"
            type={active ? 'primary' : 'default'}
            aria-pressed={active}
            disabled={key === 'my' && myState === 'loading'}
            onClick={() => onSelect(key)}
            style={{ flexShrink: 0 }}
          >
            {label}
          </Button>
        )
      })}
    </div>
  )
}

type WaitingTabProps = {
  state: ReturnType<typeof useActionItems>
  waiting: { current: ActionItem[]; otherCompanies: number }
  onRetry: () => void
  onShowAll: () => void
  onOpenOtherCompanies: () => void
}

function WaitingTab({ state, waiting, onRetry, onShowAll, onOpenOtherCompanies }: WaitingTabProps) {
  const { token } = theme.useToken()
  const { current, otherCompanies } = waiting

  if (state.loading) return <MobileStateWidget state="loading" />
  // A failed refresh leaves no items (the store counts it as zero): say so instead of «nothing waits».
  if (state.error) return <MobileStateWidget state="error" onRetry={onRetry} />

  return (
    <div style={{ display: 'grid', gap: 12, minWidth: 0 }}>
      {otherCompanies > 0 ? (
        <button
          type="button"
          className="m-list-row"
          onClick={onOpenOtherCompanies}
          style={{
            borderRadius: token.borderRadiusLG,
            background: token.colorInfoBg,
            border: `1px solid ${token.colorInfoBorder}`,
          }}
        >
          <span style={{ flex: 1, minWidth: 0 }}>В других компаниях ещё {otherCompanies}</span>
          <RightOutlined aria-hidden />
        </button>
      ) : null}
      {current.length === 0 ? (
        <MobileStateWidget
          state="empty"
          title="Нет заявок, ждущих вашего решения"
          action={<Button onClick={onShowAll}>Показать все заявки</Button>}
        />
      ) : (
        <ul aria-label="Ждут меня" style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 12 }}>
          {current.map((item) => (
            <li key={`${item.tenant?.subdomain ?? ''}:${item.id}`}>
              <RequestMobileCardFrame to={`/requests/${item.id}`} testId={`waiting-card-${item.id}`}>
                <RequestMobileCardBody
                  id={item.id}
                  statusTag={<RequestStatusToneTag tone="processing">На согласовании · шаг {item.step}</RequestStatusToneTag>}
                  title={item.title}
                  subtitle={item.type_label}
                  amount={formatRequestAmount(item.amount, item.currency)}
                  meta={[item.created_at ? formatRequestDate(item.created_at) : null]}
                />
              </RequestMobileCardFrame>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
