import type { CategorySlice } from './types'
import { CircleBreakdownWidget } from './CircleBreakdownWidget'

type IncomePieWidgetProps = {
  slices: CategorySlice[]
  loading?: boolean
}

export function IncomePieWidget({ slices, loading }: IncomePieWidgetProps) {
  return <CircleBreakdownWidget title="Доходы по категориям/статьям" slices={slices} loading={loading} />
}
