import { Navigate, useParams } from 'react-router-dom'
import { TgBankListPage, type TgBankListMode } from './TgBankListPage'

const MODES: TgBankListMode[] = ['all', 'expenses', 'revenues']

/** Route wrapper for `/tg/bank/accounts/:walletId/:mode`: validates params and shows the account's movements. */
export function TgBankAccountMovementsPage() {
  const { walletId, mode } = useParams<{ walletId: string; mode: string }>()
  const id = Number(walletId)
  if (!Number.isInteger(id) || id <= 0 || !MODES.includes(mode as TgBankListMode)) {
    return <Navigate to="/tg/bank" replace />
  }
  return <TgBankListPage mode={mode as TgBankListMode} walletId={id} />
}
