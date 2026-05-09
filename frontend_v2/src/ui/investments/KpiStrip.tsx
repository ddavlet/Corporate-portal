import { Card, Space, Typography } from 'antd'

import { asMoney, type CurrencyTotal } from './utils'

type KpiItem = {
  label: string
  value: string
  hint?: string
}

type Props = {
  totals?: CurrencyTotal[]
  totalsLabel?: string
  extra?: KpiItem[]
}

export function KpiStrip({ totals, totalsLabel = 'Итого', extra }: Props) {
  const items: KpiItem[] = []
  if (totals && totals.length > 0) {
    for (const t of totals) {
      items.push({ label: `${totalsLabel}, ${t.currency}`, value: asMoney(t.total) })
    }
  } else if (totals) {
    items.push({ label: totalsLabel, value: '0' })
  }
  for (const e of extra || []) items.push(e)
  if (items.length === 0) return null
  return (
    <Space wrap size="small" style={{ width: '100%' }}>
      {items.map((it, i) => (
        <Card key={i} size="small" style={{ minWidth: 180 }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {it.label}
          </Typography.Text>
          <div style={{ fontSize: 18, fontWeight: 600, lineHeight: 1.3 }}>{it.value}</div>
          {it.hint ? (
            <Typography.Text type="secondary" style={{ fontSize: 11 }}>
              {it.hint}
            </Typography.Text>
          ) : null}
        </Card>
      ))}
    </Space>
  )
}
