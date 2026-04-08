import { ProfitKpiWidget } from './ProfitKpiWidget'

type CashflowProfitCurrentMonthWidgetProps = {
  value: number
  loading?: boolean
}

export function CashflowProfitCurrentMonthWidget({ value, loading }: CashflowProfitCurrentMonthWidgetProps) {
  return <ProfitKpiWidget title="Прибыль Cashflow (текущий месяц)" value={value} loading={loading} />
}
