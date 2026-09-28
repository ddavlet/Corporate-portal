/**
 * «Наш» банковский счёт, с которого/на который прошло движение (Wallet → BankAccount).
 * Не путать с account_no/mfo строки выписки — это счёт контрагента.
 */
export type BankWalletAccountFields = {
  wallet_id?: number | null
  wallet_label?: string | null
  wallet_account_no?: string | null
  wallet_mfo?: string | null
}

export function formatBankWalletAccount(row: BankWalletAccountFields, options?: { withMfo?: boolean }): string {
  const label = String(row.wallet_label || '').trim()
  const accountNo = String(row.wallet_account_no || '').trim()
  const mfo = String(row.wallet_mfo || '').trim()
  let text: string
  if (label && accountNo && label !== accountNo) text = `${label} · ${accountNo}`
  else if (label || accountNo) text = label || accountNo
  else if (row.wallet_id) text = `Счёт #${row.wallet_id}`
  else return '-'
  if (options?.withMfo && mfo) text += ` (МФО ${mfo})`
  return text
}
