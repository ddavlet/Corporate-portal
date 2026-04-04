import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Skeleton, Space, Typography } from 'antd'
import { Link } from 'react-router-dom'
import {
  getBankBalances,
  getCashBalances,
  getCorporateCardBalances,
  type ChannelBalanceRow,
} from '../lib/api'

type Channel = 'cash' | 'bank' | 'corporate_card'

const loaders = {
  cash: getCashBalances,
  bank: getBankBalances,
  corporate_card: getCorporateCardBalances,
} as const

const emptySettingsHref: Record<Channel, string> = {
  cash: '/settings/cash-registers',
  bank: '/settings',
  corporate_card: '/settings',
}

function formatLine(row: ChannelBalanceRow): string {
  const n = Number(row.current_balance)
  const amount = Number.isNaN(n)
    ? `${row.current_balance} ${row.currency}`.trim()
    : `${n.toLocaleString('ru-RU')} ${row.currency}`.trim()
  const label = row.display_name || row.currency
  return `${label}: ${amount}`
}

export function ChannelBalancesSummary({ channel }: { channel: Channel }) {
  const [loading, setLoading] = useState(true)
  const [rows, setRows] = useState<ChannelBalanceRow[]>([])
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await loaders[channel]()
      setRows(data)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [channel])

  useEffect(() => {
    void load()
  }, [load])

  if (loading) {
    return <Skeleton active title={{ width: 200 }} paragraph={{ rows: 1 }} style={{ marginBottom: 16 }} />
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
        style={{ marginBottom: 16 }}
      />
    )
  }

  if (rows.length === 0) {
    return (
      <Card size="small" style={{ marginBottom: 16 }}>
        <Typography.Text type="secondary">
          Остатки не настроены или нет данных.{' '}
          <Link to={emptySettingsHref[channel]}>Перейти в настройки</Link>
        </Typography.Text>
      </Card>
    )
  }

  return (
    <Card size="small" title="Остатки по кошелькам" style={{ marginBottom: 16 }}>
      <Space direction="vertical" size={4} style={{ width: '100%' }}>
        {rows.map((row) => (
          <Typography.Text key={row.wallet_id}>{formatLine(row)}</Typography.Text>
        ))}
      </Space>
    </Card>
  )
}
