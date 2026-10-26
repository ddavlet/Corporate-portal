import { useEffect, useState, type CSSProperties } from 'react'
import { Alert } from 'antd'
import { getKapitalbankPendingAccounts, type KapitalbankPendingAccount } from '../lib/api'

export function KapitalbankPendingAccountsWidget({ style }: { style?: CSSProperties } = {}) {
  const [accounts, setAccounts] = useState<KapitalbankPendingAccount[]>([])

  useEffect(() => {
    let cancelled = false
    getKapitalbankPendingAccounts()
      .then((data) => {
        if (!cancelled) setAccounts(data.enabled ? data.accounts : [])
      })
      .catch((e) => {
        console.warn('Kapitalbank pending accounts request failed', e)
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (accounts.length === 0) return null

  return (
    <Alert
      type="warning"
      showIcon
      style={style}
      message={`Требуется решение по счетам в банке: ${accounts.length}`}
      description={
        <div>
          <ul style={{ margin: 0, paddingLeft: 20 }}>
            {accounts.map((a) => (
              <li key={`${a.branch}-${a.account_no}`}>
                {a.account_no} · {a.name} · {a.currency} · {a.balance ?? '—'}
              </li>
            ))}
          </ul>
          <div>Решение по счёту принимает администратор в админке портала.</div>
        </div>
      }
    />
  )
}
