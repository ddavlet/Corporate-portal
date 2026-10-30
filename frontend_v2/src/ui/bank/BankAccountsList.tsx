import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Col, Collapse, Row, Skeleton, Space, Tag, Typography } from 'antd'
import { Link } from 'react-router-dom'
import {
  getBankAccountsOverview,
  getKapitalbankUntrackedAccounts,
  type BankAccountOverviewDto,
  type KapitalbankUntrackedAccountDto,
} from '../../lib/api'
import { formatExact } from '../../lib/reportsFormat'

function formatBalance(value: string | null | undefined, currency: string): string {
  const amount = formatExact(value)
  return amount === '—' ? amount : `${amount} ${currency}`.trim()
}

function AccountTypeTag({ type }: { type: BankAccountOverviewDto['account_type'] }) {
  if (type === 'controlled') return <Tag color="blue">Контроль</Tag>
  if (type === 'informational') return <Tag>Информационный</Tag>
  return <Tag>Служебный</Tag>
}

function AccountCard({ account }: { account: BankAccountOverviewDto }) {
  return (
    <Link to={`/bank/accounts/${account.wallet_id}`} style={{ display: 'block' }}>
      <Card hoverable size="small" styles={{ body: { padding: 16 } }}>
        <Space direction="vertical" size={4} style={{ width: '100%' }}>
          <Space size={8} wrap>
            <Typography.Text strong>{account.label || account.account_no || `Счёт #${account.wallet_id}`}</Typography.Text>
            <AccountTypeTag type={account.account_type} />
          </Space>
          {account.account_no ? <Typography.Text type="secondary">{account.account_no}</Typography.Text> : null}
          <Typography.Text>{formatBalance(account.current_balance, account.currency)}</Typography.Text>
        </Space>
      </Card>
    </Link>
  )
}

function AccountCardsRow({ accounts }: { accounts: BankAccountOverviewDto[] }) {
  return (
    <Row gutter={[16, 16]}>
      {accounts.map((account) => (
        <Col key={account.wallet_id} xs={24} sm={12} lg={8}>
          <AccountCard account={account} />
        </Col>
      ))}
    </Row>
  )
}

function ServiceAndUntrackedList({
  service,
  untracked,
}: {
  service: BankAccountOverviewDto[]
  untracked: KapitalbankUntrackedAccountDto[]
}) {
  return (
    <Space direction="vertical" size={4} style={{ width: '100%' }}>
      {service.map((account) => (
        <div key={`wallet-${account.wallet_id}`}>
          <Typography.Text>
            {[account.label, account.account_no].filter(Boolean).join(' · ')} ·{' '}
            {formatBalance(account.current_balance, account.currency)}
          </Typography.Text>{' '}
          <Tag>Служебный</Tag>
        </div>
      ))}
      {untracked.map((account) => (
        <div key={`untracked-${account.branch}-${account.account_no}`}>
          <Typography.Text>
            {[account.account_no, account.name].filter(Boolean).join(' · ')} ·{' '}
            {formatBalance(account.balance, account.currency)}
          </Typography.Text>{' '}
          {account.status === 'pending' ? <Tag color="orange">Ожидает решения</Tag> : <Tag>Служебный</Tag>}
          {account.reason ? <Typography.Text type="secondary"> {account.reason}</Typography.Text> : null}
        </div>
      ))}
    </Space>
  )
}

/** Bank accounts of the tenant as cards: controlled first, then informational; service and untracked ones folded away. */
export function BankAccountsList() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [accounts, setAccounts] = useState<BankAccountOverviewDto[]>([])
  const [untracked, setUntracked] = useState<KapitalbankUntrackedAccountDto[]>([])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    const untrackedRequest = getKapitalbankUntrackedAccounts().catch((e: unknown) => {
      // The kapitalbank block is auxiliary: without it the page still shows the portal's own accounts.
      console.warn('Kapitalbank untracked accounts request failed', e)
      return [] as KapitalbankUntrackedAccountDto[]
    })
    try {
      const [overview, untrackedRows] = await Promise.all([getBankAccountsOverview(), untrackedRequest])
      setAccounts(overview)
      setUntracked(untrackedRows)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  if (loading) {
    return <Skeleton active title={{ width: 200 }} paragraph={{ rows: 2 }} />
  }

  if (error) {
    return (
      <Alert
        type="error"
        showIcon
        message={error}
        action={
          <Button size="small" onClick={() => void load()}>
            Повторить
          </Button>
        }
      />
    )
  }

  const controlled = accounts.filter((a) => a.account_type === 'controlled')
  const informational = accounts.filter((a) => a.account_type === 'informational')
  const service = accounts.filter((a) => a.account_type !== 'controlled' && a.account_type !== 'informational')
  const hiddenCount = service.length + untracked.length

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {controlled.length === 0 && informational.length === 0 ? (
        <Typography.Text type="secondary">
          Банковские счета не настроены. <Link to="/settings">Перейти в настройки</Link>
        </Typography.Text>
      ) : null}
      {controlled.length > 0 ? <AccountCardsRow accounts={controlled} /> : null}
      {informational.length > 0 ? <AccountCardsRow accounts={informational} /> : null}
      {hiddenCount > 0 ? (
        <Collapse
          size="small"
          items={[
            {
              key: 'hidden',
              label: `Служебные и неразобранные (${hiddenCount})`,
              children: <ServiceAndUntrackedList service={service} untracked={untracked} />,
            },
          ]}
        />
      ) : null}
    </Space>
  )
}
