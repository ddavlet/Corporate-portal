import { Card, Statistic } from 'antd'

type ProfitKpiWidgetProps = {
  title: string
  value: number
  loading?: boolean
}

export function ProfitKpiWidget({ title, value, loading }: ProfitKpiWidgetProps) {
  return (
    <Card loading={loading}>
      <Statistic
        title={title}
        value={value}
        precision={2}
        valueStyle={{ color: value >= 0 ? '#3f8600' : '#cf1322' }}
      />
    </Card>
  )
}
