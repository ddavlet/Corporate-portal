import { act, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { KapitalbankPendingAccountsWidget } from './KapitalbankPendingAccountsWidget'

const getPendingMock = vi.fn()

vi.mock('../lib/api', () => ({
  getKapitalbankPendingAccounts: (...args: unknown[]) => getPendingMock(...args),
}))

const ACC = (no: string, balance: string | null) => ({
  account_no: no,
  branch: '00001',
  name: 'Основной',
  currency: 'UZS',
  balance,
  first_seen_at: '2026-10-26T10:00:00Z',
})

describe('KapitalbankPendingAccountsWidget', () => {
  beforeEach(() => {
    getPendingMock.mockReset()
    vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  it('renders count and accounts when pending', async () => {
    getPendingMock.mockResolvedValue({ enabled: true, accounts: [ACC('20208000111', '100.50'), ACC('20208000222', null)] })
    render(<KapitalbankPendingAccountsWidget />)
    expect(await screen.findByText('Требуется решение по счетам в банке: 2')).toBeTruthy()
    expect(screen.getByText('20208000111 · Основной · UZS · 100,50')).toBeTruthy()
    expect(screen.getByText('20208000222 · Основной · UZS · —')).toBeTruthy()
    expect(screen.getByText('Решение по счёту принимает администратор в админке портала.')).toBeTruthy()
  })

  it('renders nothing when disabled', async () => {
    getPendingMock.mockResolvedValue({ enabled: false, accounts: [ACC('20208000111', null)] })
    const { container } = render(<KapitalbankPendingAccountsWidget />)
    await waitFor(() => expect(getPendingMock).toHaveBeenCalled())
    await act(async () => {
      await Promise.resolve()
    })
    expect(container.innerHTML).toBe('')
  })

  it('renders nothing when list empty', async () => {
    getPendingMock.mockResolvedValue({ enabled: true, accounts: [] })
    const { container } = render(<KapitalbankPendingAccountsWidget />)
    await waitFor(() => expect(getPendingMock).toHaveBeenCalled())
    await act(async () => {
      await Promise.resolve()
    })
    expect(container.innerHTML).toBe('')
  })

  it('renders nothing on request error', async () => {
    getPendingMock.mockRejectedValue(new Error('403'))
    const { container } = render(<KapitalbankPendingAccountsWidget />)
    await waitFor(() => expect(console.warn).toHaveBeenCalled())
    await act(async () => {
      await Promise.resolve()
    })
    expect(container.innerHTML).toBe('')
  })
})
