import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { BankAccountsList } from './BankAccountsList'

const getOverviewMock = vi.fn()
const getUntrackedMock = vi.fn()

vi.mock('../../lib/api', () => ({
  getBankAccountsOverview: (...args: unknown[]) => getOverviewMock(...args),
  getKapitalbankUntrackedAccounts: (...args: unknown[]) => getUntrackedMock(...args),
}))

const ACCOUNT = (
  walletId: number,
  label: string,
  accountNo: string,
  accountType: 'controlled' | 'informational' | 'service',
) => ({
  wallet_id: walletId,
  bank_account_id: walletId + 100,
  label,
  account_no: accountNo,
  mfo: '00001',
  is_default: false,
  account_type: accountType,
  currency: 'UZS',
  current_balance: '1500.00',
})

const OVERVIEW = [
  ACCOUNT(12, 'Валютный', '20208000000000000002', 'informational'),
  ACCOUNT(11, 'Основной', '20208000000000000001', 'controlled'),
  ACCOUNT(13, 'Транзитный', '20208000000000000003', 'service'),
]

function renderList() {
  return render(
    <MemoryRouter>
      <BankAccountsList />
    </MemoryRouter>,
  )
}

describe('BankAccountsList', () => {
  beforeEach(() => {
    getOverviewMock.mockReset()
    getUntrackedMock.mockReset()
    vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  it('shows controlled before informational accounts and folds service ones away', async () => {
    getOverviewMock.mockResolvedValue(OVERVIEW)
    getUntrackedMock.mockResolvedValue([])
    renderList()

    expect(await screen.findByText('Основной')).toBeTruthy()
    const links = screen.getAllByRole('link').filter((a) => a.getAttribute('href')?.startsWith('/bank/accounts/'))
    expect(links.map((a) => a.getAttribute('href'))).toEqual(['/bank/accounts/11', '/bank/accounts/12'])
    expect(links[0].textContent).toContain('Контроль')
    expect(links[0].textContent).toContain('20208000000000000001')
    expect(links[1].textContent).toContain('Информационный')

    // The service account lives in the collapsed block and is not a link.
    expect(screen.queryByText(/Транзитный/)).toBeNull()
    fireEvent.click(screen.getByText('Служебные и неразобранные (1)'))
    const serviceLine = await screen.findByText(/Транзитный/)
    expect(serviceLine.closest('a')).toBeNull()
  })

  it('links an account card to its page', async () => {
    getOverviewMock.mockResolvedValue([ACCOUNT(11, 'Основной', '20208000000000000001', 'controlled')])
    getUntrackedMock.mockResolvedValue([])
    renderList()

    const label = await screen.findByText('Основной')
    expect(label.closest('a')?.getAttribute('href')).toBe('/bank/accounts/11')
  })

  it('shows untracked kapitalbank accounts in the collapsed block', async () => {
    getOverviewMock.mockResolvedValue([ACCOUNT(11, 'Основной', '20208000000000000001', 'controlled')])
    getUntrackedMock.mockResolvedValue([
      {
        account_no: '20208000000000000009',
        branch: '00001',
        name: 'Новый счёт',
        currency: 'UZS',
        balance: null,
        status: 'pending',
        reason: '',
      },
    ])
    renderList()

    fireEvent.click(await screen.findByText('Служебные и неразобранные (1)'))
    const line = await screen.findByText(/20208000000000000009/)
    expect(line.closest('a')).toBeNull()
    expect(screen.getByText('Ожидает решения')).toBeTruthy()
  })

  it('hides the untracked block when kapitalbank returns nothing', async () => {
    getOverviewMock.mockResolvedValue([ACCOUNT(11, 'Основной', '20208000000000000001', 'controlled')])
    getUntrackedMock.mockResolvedValue([])
    renderList()

    expect(await screen.findByText('Основной')).toBeTruthy()
    expect(screen.queryByText(/Служебные и неразобранные/)).toBeNull()
  })

  it('still shows accounts when the kapitalbank request fails', async () => {
    getOverviewMock.mockResolvedValue([ACCOUNT(11, 'Основной', '20208000000000000001', 'controlled')])
    getUntrackedMock.mockRejectedValue(new Error('500'))
    renderList()

    expect(await screen.findByText('Основной')).toBeTruthy()
    await waitFor(() => expect(console.warn).toHaveBeenCalled())
    await act(async () => {
      await Promise.resolve()
    })
    expect(screen.queryByText(/Служебные и неразобранные/)).toBeNull()
  })
})
