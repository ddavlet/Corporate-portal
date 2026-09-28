import { describe, expect, it } from 'vitest'
import type { StatementLineItem } from '../../../../lib/reportsApi'
import { drillGroupings, groupDrillItems } from './drillGroups'

const item = (id: string, amount: string, over: Partial<StatementLineItem> = {}): StatementLineItem => ({
  entry_id: id,
  date: '2026-08-05',
  amount,
  section: 'operational',
  source: 'request',
  category: 'Аренда',
  title: `Заявка ${id}`,
  counterparty: 'ООО Офис',
  request_id: Number(id),
  channel: '',
  line_id: 'opex.1',
  line_label: 'Аренда',
  amortization: null,
  ...over,
})

describe('groupDrillItems', () => {
  const items = [
    item('1', '100'),
    item('2', '300', { counterparty: ' ооо  офис ', date: '2026-07-10' }),
    item('3', '600', { counterparty: 'ИП Склад' }),
    item('4', '0', { counterparty: '', source: 'bank', request_id: null, line_label: 'Банк' }),
  ]

  it('lists operations largest first with their share', () => {
    const groups = groupDrillItems(items, 'item')
    expect(groups.map((g) => g.key)).toEqual(['3', '2', '1', '4'])
    expect(groups[0].share).toBeCloseTo(0.6)
  })

  it('groups one vendor however it was typed, and bank lines by their line', () => {
    const groups = groupDrillItems(items, 'vendor')
    expect(groups.map((g) => [g.label, g.amount, g.items.length])).toEqual([
      ['ИП Склад', 600, 1],
      ['ООО Офис', 400, 2],
      ['Банк', 0, 1],
    ])
  })

  it('groups by month in calendar order', () => {
    expect(groupDrillItems(items, 'month').map((g) => g.label)).toEqual(['Июль 2026', 'Август 2026'])
  })
})

describe('drillGroupings', () => {
  it('offers months only for a span longer than a month and names sources when there are no requests', () => {
    expect(drillGroupings(1, true).map((o) => o.label)).toEqual(['По заявкам', 'По поставщикам'])
    expect(drillGroupings(9, false).map((o) => o.label)).toEqual(['По операциям', 'По источникам', 'По месяцам'])
  })
})
