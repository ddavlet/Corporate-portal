import { Card, Empty, Space, Typography } from 'antd'
import type { CategorySlice } from './types'

type CircleBreakdownWidgetProps = {
  title: string
  slices: CategorySlice[]
  loading?: boolean
}

const COLORS = ['#1677ff', '#13c2c2', '#52c41a', '#faad14', '#eb2f96', '#722ed1', '#fa541c', '#2f54eb']

function buildGradient(slices: CategorySlice[]): string {
  const total = slices.reduce((acc, item) => acc + item.amount, 0)
  if (total <= 0) return '#f0f0f0'
  let start = 0
  const parts: string[] = []
  slices.forEach((slice, index) => {
    const pct = (slice.amount / total) * 100
    const end = start + pct
    parts.push(`${COLORS[index % COLORS.length]} ${start}% ${end}%`)
    start = end
  })
  return `conic-gradient(${parts.join(', ')})`
}

export function CircleBreakdownWidget({ title, slices, loading }: CircleBreakdownWidgetProps) {
  const total = slices.reduce((acc, item) => acc + item.amount, 0)
  const topSlices = slices.slice(0, 6)
  return (
    <Card title={title} loading={loading}>
      {!slices.length ? (
        <Empty description="Нет данных для диаграммы" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <Space align="start" size={24} wrap>
          <div
            style={{
              width: 180,
              height: 180,
              borderRadius: '50%',
              background: buildGradient(topSlices),
              position: 'relative',
              flex: '0 0 auto',
            }}
          >
            <div
              style={{
                position: 'absolute',
                width: 86,
                height: 86,
                borderRadius: '50%',
                background: '#fff',
                inset: '50%',
                transform: 'translate(-50%, -50%)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Typography.Text strong>{new Intl.NumberFormat('ru-RU').format(total)}</Typography.Text>
            </div>
          </div>
          <Space direction="vertical" size={6}>
            {topSlices.map((slice, index) => (
              <Space key={`${slice.label}-${index}`} size={8}>
                <div style={{ width: 10, height: 10, borderRadius: 6, background: COLORS[index % COLORS.length] }} />
                <Typography.Text>{slice.label}</Typography.Text>
                <Typography.Text type="secondary">{new Intl.NumberFormat('ru-RU').format(slice.amount)}</Typography.Text>
              </Space>
            ))}
          </Space>
        </Space>
      )}
    </Card>
  )
}
