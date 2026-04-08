import { ProfitKpiWidget } from './ProfitKpiWidget'

type PnlNetProfitPrevMonthWidgetProps = {
  value: number
  loading?: boolean
}

export function PnlNetProfitPrevMonthWidget({ value, loading }: PnlNetProfitPrevMonthWidgetProps) {
  return <ProfitKpiWidget title="Чистая прибыль P&L (прошлый месяц)" value={value} loading={loading} />
}
