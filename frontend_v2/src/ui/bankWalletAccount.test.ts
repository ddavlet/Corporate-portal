import { describe, expect, it } from 'vitest'
import { formatBankWalletAccount } from './bankWalletAccount'

describe('formatBankWalletAccount', () => {
  it('joins label and account number', () => {
    expect(formatBankWalletAccount({ wallet_id: 1, wallet_label: 'Основной', wallet_account_no: '2020800055' })).toBe(
      'Основной · 2020800055',
    )
  })

  it('does not duplicate when label equals account number', () => {
    expect(formatBankWalletAccount({ wallet_label: '2020800055', wallet_account_no: '2020800055' })).toBe('2020800055')
  })

  it('falls back to label only (default account without number)', () => {
    expect(formatBankWalletAccount({ wallet_id: 3, wallet_label: 'Основной', wallet_account_no: '' })).toBe('Основной')
  })

  it('falls back to wallet id, then dash', () => {
    expect(formatBankWalletAccount({ wallet_id: 7 })).toBe('Счёт #7')
    expect(formatBankWalletAccount({})).toBe('-')
  })

  it('appends MFO on request', () => {
    expect(
      formatBankWalletAccount(
        { wallet_label: 'Второй', wallet_account_no: '2020800055', wallet_mfo: '00444' },
        { withMfo: true },
      ),
    ).toBe('Второй · 2020800055 (МФО 00444)')
  })
})
