import type { CategorySlice } from './types'
import { CircleBreakdownWidget } from './CircleBreakdownWidget'

type ExpensePieWidgetProps = {
  slices: CategorySlice[]
  loading?: boolean
}

export function ExpensePieWidget({ slices, loading }: ExpensePieWidgetProps) {
  return <CircleBreakdownWidget title="Расходы по категориям/статьям" slices={slices} loading={loading} />
}
