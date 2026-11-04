import { useEffect, useState } from 'react'
import { Alert, Button, Card, Space, Tabs, Typography } from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { getBankAccountsOverview, type BankAccountOverviewDto } from '../lib/api'
import { BankSectionPage, type BankSectionMode } from './BankSectionPage'

const TAB_ITEMS: { key: BankSectionMode; label: string }[] = [
  { key: 'all', label: 'Все' },
  { key: 'expenses', label: 'Расходы' },
  { key: 'revenues', label: 'Доходы' },
]

function parseTab(value: string | null): BankSectionMode {
  return value === 'expenses' || value === 'revenues' ? value : 'all'
}

function parseWalletId(value: string | undefined): number | null {
  if (!value || !/^\d+$/.test(value)) return null
  const n = Number(value)
  return n > 0 ? n : null
}

/** Movements of one bank account: header with the account, tabs «Все» / «Расходы» / «Доходы» (in ?tab=). */
export function BankAccountPage() {
  const navigate = useNavigate()
  const params = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const walletId = parseWalletId(params.walletId)
  const tab = parseTab(searchParams.get('tab'))
  const [account, setAccount] = useState<BankAccountOverviewDto | null>(null)

  useEffect(() => {
    if (walletId === null) return
    let cancelled = false
    setAccount(null)
    getBankAccountsOverview()
      .then((accounts) => {
        if (!cancelled) setAccount(accounts.find((a) => a.wallet_id === walletId) ?? null)
      })
      .catch((e) => {
        // The header falls back to the wallet number; the movements below still load.
        console.warn('Bank accounts overview request failed', e)
      })
    return () => {
      cancelled = true
    }
  }, [walletId])

  const backButton = (
    <Space style={{ marginBottom: 12 }}>
      <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/bank')}>
        Банк
      </Button>
    </Space>
  )

  if (walletId === null) {
    return (
      <Card>
        {backButton}
        <Alert type="warning" showIcon message="Счёт не найден" />
      </Card>
    )
  }

  const title = account?.label || account?.account_no || `Счёт #${walletId}`
  const accountNo = account?.account_no && account.account_no !== title ? account.account_no : ''

  return (
    <>
      <Card style={{ marginBottom: 16 }}>
        {backButton}
        <Typography.Title level={4} style={{ marginTop: 0, marginBottom: accountNo ? 4 : 0 }}>
          {title}
        </Typography.Title>
        {accountNo ? <Typography.Text type="secondary">{accountNo}</Typography.Text> : null}
        <Tabs
          style={{ marginTop: 12, marginBottom: -16 }}
          activeKey={tab}
          onChange={(key) => {
            const next = new URLSearchParams(searchParams)
            if (key === 'all') next.delete('tab')
            else next.set('tab', key)
            setSearchParams(next, { replace: true })
          }}
          items={TAB_ITEMS}
        />
      </Card>
      <BankSectionPage key={walletId} mode={tab} walletId={walletId} />
    </>
  )
}
