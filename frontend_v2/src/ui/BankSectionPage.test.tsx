import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { BankSectionPage } from './BankSectionPage'

const getBankAccountsMock = vi.fn()
const getOverviewMock = vi.fn()
const useInfiniteListMock = vi.fn()

vi.mock('../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../lib/api')>('../lib/api')
  return {
    ...actual,
    apiFetch: vi.fn(),
    getBankAccounts: (...args: unknown[]) => getBankAccountsMock(...args),
    getBankAccountsOverview: (...args: unknown[]) => getOverviewMock(...args),
  }
})

vi.mock('../lib/useInfiniteList', () => ({
  useInfiniteList: (options: { url: string; enabled?: boolean }) => useInfiniteListMock(options),
}))

vi.mock('../lib/useFinanceInfiniteScrollFooter', () => ({
  useFinanceInfiniteScrollFooter: () => ({
    sentinelRef: { current: null },
    hasMore: false,
    loadingMore: false,
    loadMoreAll: vi.fn(),
  }),
}))

vi.mock('./KapitalbankPendingAccountsWidget', () => ({
  KapitalbankPendingAccountsWidget: () => <div>KapitalbankPendingAccountsWidget</div>,
}))

vi.mock('./ChannelBalancesSummary', () => ({
  ChannelBalancesSummary: () => <div>ChannelBalancesSummary</div>,
}))

const OVERVIEW_ROW = (walletId: number, accountType: 'controlled' | 'informational' | 'service') => ({
  wallet_id: walletId,
  bank_account_id: walletId + 100,
  label: 'Основной',
  account_no: '20208000000000000001',
  mfo: '00001',
  is_default: true,
  account_type: accountType,
  currency: 'UZS',
  current_balance: '0.00',
})

function renderPage(props: Parameters<typeof BankSectionPage>[0]) {
  return render(
    <MemoryRouter>
      <BankSectionPage {...props} />
    </MemoryRouter>,
  )
}

/** The «Наш счёт» filter Select; the table also has a «Наш счёт» column header. */
function walletSelectPlaceholder(): HTMLElement | undefined {
  return screen.queryAllByText('Наш счёт').find((el) => el.classList.contains('ant-select-selection-placeholder'))
}

async function openAdvancedFilters() {
  fireEvent.click(screen.getByText('Расширенные фильтры'))
  await screen.findByText('Сбросить фильтры')
}

describe('BankSectionPage', () => {
  beforeEach(() => {
    getBankAccountsMock.mockReset()
    getBankAccountsMock.mockResolvedValue([])
    getOverviewMock.mockReset()
    useInfiniteListMock.mockReset()
    useInfiniteListMock.mockReturnValue({
      items: [],
      loading: false,
      loadingMore: false,
      error: null,
      hasMore: false,
      loadMore: vi.fn(),
      reload: vi.fn(),
    })
  })

  it('keeps the common list header without walletId', async () => {
    renderPage({ mode: 'all' })

    expect(screen.getByText('Банк')).toBeInTheDocument()
    expect(screen.getByText('Банк — все операции')).toBeInTheDocument()
    expect(screen.getByText('KapitalbankPendingAccountsWidget')).toBeInTheDocument()
    expect(screen.getByText('ChannelBalancesSummary')).toBeInTheDocument()
    expect(getOverviewMock).not.toHaveBeenCalled()
    await waitFor(() => expect(getBankAccountsMock).toHaveBeenCalled())

    await openAdvancedFilters()
    expect(walletSelectPlaceholder()).toBeTruthy()
    expect(screen.getByText('Без заявки (обязательна)')).toBeInTheDocument()
  })

  it('renders only the list of one account with walletId', async () => {
    getOverviewMock.mockResolvedValue([OVERVIEW_ROW(11, 'controlled')])
    renderPage({ mode: 'all', walletId: 11 })

    await waitFor(() => expect(getOverviewMock).toHaveBeenCalled())
    await act(async () => {
      await Promise.resolve()
    })
    expect(screen.queryByText('Банк')).toBeNull()
    expect(screen.queryByText('Банк — все операции')).toBeNull()
    expect(screen.queryByText('KapitalbankPendingAccountsWidget')).toBeNull()
    expect(screen.queryByText('ChannelBalancesSummary')).toBeNull()

    // Both lists are requested for this wallet only.
    const urls = useInfiniteListMock.mock.calls.map(([options]) => (options as { url: string }).url)
    expect(urls).toContain('/api/bank/expenses/?wallet=11')
    expect(urls).toContain('/api/bank/revenues/?wallet=11')

    await openAdvancedFilters()
    expect(walletSelectPlaceholder()).toBeUndefined()
    expect(screen.getByText('Без заявки (обязательна)')).toBeInTheDocument()
  })

  it('hides the «без заявки» switch on an informational account', async () => {
    getOverviewMock.mockResolvedValue([OVERVIEW_ROW(12, 'informational')])
    renderPage({ mode: 'expenses', walletId: 12 })

    await waitFor(() => expect(getOverviewMock).toHaveBeenCalled())
    await openAdvancedFilters()
    await waitFor(() => expect(screen.queryByText('Без заявки (обязательна)')).toBeNull())
  })
})
