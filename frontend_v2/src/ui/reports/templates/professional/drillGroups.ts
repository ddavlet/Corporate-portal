import type { StatementLineItem } from '../../../../lib/reportsApi'
import { MONTH_NAMES } from '../../../../lib/reportsFormat'

export type DrillGrouping = 'item' | 'vendor' | 'month'

export type DrillGroup = { key: string; label: string; amount: number; share: number; items: StatementLineItem[] }

/** The composition bar shows at most this many segments; the cards list everything. */
export const MAX_STACK_SEGMENTS = 24

const normalize = (text: string) => text.split(/\s+/).filter(Boolean).join(' ').toLocaleLowerCase('ru')
const monthLabel = (key: string) => `${MONTH_NAMES[Number(key.slice(5, 7)) - 1]} ${key.slice(0, 4)}`

function keyAndLabel(item: StatementLineItem, grouping: 'vendor' | 'month'): [string, string] {
  if (grouping === 'month') return [item.date.slice(0, 7), monthLabel(item.date.slice(0, 7))]
  const vendor = item.counterparty.trim()
  // Bank and cash lines have no vendor: they group by the statement line they belong to.
  return vendor ? [normalize(vendor), vendor] : [`line:${item.line_id}`, item.line_label]
}

export function groupDrillItems(items: StatementLineItem[], grouping: DrillGrouping): DrillGroup[] {
  const total = items.reduce((sum, item) => sum + Number(item.amount), 0)
  const share = (amount: number) => (total > 0 ? amount / total : 0)
  if (grouping === 'item') {
    return items
      .map((item) => ({ key: item.entry_id, label: item.title, amount: Number(item.amount), share: share(Number(item.amount)), items: [item] }))
      .sort((a, b) => b.amount - a.amount)
  }
  const groups = new Map<string, DrillGroup>()
  for (const item of items) {
    const [key, label] = keyAndLabel(item, grouping)
    const group = groups.get(key) ?? { key, label, amount: 0, share: 0, items: [] }
    group.amount += Number(item.amount)
    group.items.push(item)
    groups.set(key, group)
  }
  const list = [...groups.values()].map((group) => ({ ...group, share: share(group.amount) }))
  return grouping === 'month' ? list.sort((a, b) => a.key.localeCompare(b.key)) : list.sort((a, b) => b.amount - a.amount)
}

export function drillGroupings(monthsInColumn: number, hasRequests: boolean): { value: DrillGrouping; label: string }[] {
  const options: { value: DrillGrouping; label: string }[] = [
    { value: 'item', label: hasRequests ? 'По заявкам' : 'По операциям' },
    { value: 'vendor', label: hasRequests ? 'По поставщикам' : 'По источникам' },
  ]
  if (monthsInColumn > 1) options.push({ value: 'month', label: 'По месяцам' })
  return options
}
