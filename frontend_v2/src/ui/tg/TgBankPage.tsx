import { useEffect, useState } from 'react'
import { Skeleton, Tag, Typography } from 'antd'
import { useNavigate } from 'react-router-dom'
import { AppstoreOutlined, ArrowDownOutlined, ArrowUpOutlined, BankOutlined } from '@ant-design/icons'
import {
  getBankAccountsOverview,
  getKapitalbankUntrackedAccounts,
  type BankAccountOverviewDto,
  type KapitalbankUntrackedAccountDto,
} from '../../lib/api'
import { formatExact } from '../../lib/reportsFormat'
import { tgHaptic } from './tgHaptic'

function formatBalance(value: string | null | undefined, currency: string): string {
  const amount = formatExact(value)
  return amount === '—' ? amount : `${amount} ${currency}`.trim()
}

type Tile = {
  key: string
  title: string
  subtitle: string
  path: string
  icon: React.ReactNode
  iconClass?: string
}

const TILES: Tile[] = [
  {
    key: 'all',
    title: 'Все операции',
    subtitle: 'Расходы и доходы в одном списке',
    path: '/tg/bank/all',
    icon: <AppstoreOutlined />,
  },
  {
    key: 'expenses',
    title: 'Расходы',
    subtitle: 'Платежи со счетов',
    path: '/tg/bank/expenses',
    icon: <ArrowUpOutlined />,
    iconClass: 'tg-section-tile-icon--expense',
  },
  {
    key: 'revenues',
    title: 'Доходы',
    subtitle: 'Поступления на счета',
    path: '/tg/bank/revenues',
    icon: <ArrowDownOutlined />,
    iconClass: 'tg-section-tile-icon--revenue',
  },
]

export function TgBankPage() {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(true)
  const [accounts, setAccounts] = useState<BankAccountOverviewDto[]>([])
  const [untracked, setUntracked] = useState<KapitalbankUntrackedAccountDto[]>([])

  useEffect(() => {
    let cancelled = false
    const run = async () => {
      // Both blocks are auxiliary: the common lists below stay available if either request fails.
      const [overview, untrackedRows] = await Promise.all([
        getBankAccountsOverview().catch((e: unknown) => {
          console.warn('Bank accounts overview request failed', e)
          return [] as BankAccountOverviewDto[]
        }),
        getKapitalbankUntrackedAccounts().catch((e: unknown) => {
          console.warn('Kapitalbank untracked accounts request failed', e)
          return [] as KapitalbankUntrackedAccountDto[]
        }),
      ])
      if (cancelled) return
      setAccounts(overview)
      setUntracked(untrackedRows)
      setLoading(false)
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [])

  const tracked = [
    ...accounts.filter((a) => a.account_type === 'controlled'),
    ...accounts.filter((a) => a.account_type === 'informational'),
  ]
  const hiddenCount =
    accounts.filter((a) => a.account_type !== 'controlled' && a.account_type !== 'informational').length +
    untracked.length

  return (
    <div className="tg-bank-page">
      <Typography.Title level={4} style={{ margin: '0 0 16px', fontWeight: 700 }}>
        Банк
      </Typography.Title>
      {loading ? <Skeleton active paragraph={{ rows: 2 }} /> : null}
      {tracked.length > 0 ? (
        <div className="tg-section-landing" style={{ marginBottom: 16 }}>
          {tracked.map((account) => (
            <button
              key={account.wallet_id}
              type="button"
              className="tg-section-tile"
              onClick={() => { tgHaptic.tap(); navigate(`/tg/bank/accounts/${account.wallet_id}/all`) }}
            >
              <span className="tg-section-tile-icon" aria-hidden>
                <BankOutlined />
              </span>
              <span className="tg-section-tile-text">
                <span className="tg-section-tile-title">
                  {account.label || account.account_no || `Счёт #${account.wallet_id}`}{' '}
                  {account.account_type === 'controlled' ? <Tag color="blue">Контроль</Tag> : <Tag>Информационный</Tag>}
                </span>
                <span className="tg-section-tile-subtitle">
                  {[account.account_no, formatBalance(account.current_balance, account.currency)]
                    .filter(Boolean)
                    .join(' · ')}
                </span>
              </span>
            </button>
          ))}
        </div>
      ) : null}
      {hiddenCount > 0 ? (
        <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
          Служебных и неразобранных счетов: {hiddenCount}
        </Typography.Paragraph>
      ) : null}
      <div className="tg-section-landing">
        {TILES.map((tile) => (
          <button
            key={tile.key}
            type="button"
            className="tg-section-tile"
            onClick={() => { tgHaptic.tap(); navigate(tile.path) }}
          >
            <span className={`tg-section-tile-icon ${tile.iconClass || ''}`.trim()} aria-hidden>
              {tile.icon}
            </span>
            <span className="tg-section-tile-text">
              <span className="tg-section-tile-title">{tile.title}</span>
              <span className="tg-section-tile-subtitle">{tile.subtitle}</span>
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}
