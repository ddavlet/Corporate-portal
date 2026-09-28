import { describe, expect, it } from 'vitest'
import type { StatementColumn } from '../../../../lib/reportsApi'
import { phoneChipOptions, phoneColumnKeys, phonePeriodColumns, resolvePhoneColumnKey } from './phoneColumns'
import { STATEMENT } from './testStatement'

const column = (key: string, kind: StatementColumn['kind'], to: string | null): StatementColumn => ({
  key,
  kind,
  label: key,
  sublabel: '',
  months: [],
  from: to ? `${to.slice(0, 8)}01` : null,
  to,
  partial: false,
  before_start: false,
  starts_before_data: false,
  delta_of: null,
})

const MONTH_PACK = [
  column('2026-08', 'period', '2026-08-31'),
  column('2026-07', 'period', '2026-07-31'),
  column('delta_prev', 'delta', null),
  column('2025-08', 'period', '2025-08-31'),
  column('delta_yoy', 'delta', null),
  column('ytd', 'total', '2026-08-31'),
]

describe('phone columns', () => {
  it('starts with the latest period', () => {
    expect(resolvePhoneColumnKey(STATEMENT.columns, null)).toBe('2026-09')
    expect(resolvePhoneColumnKey(MONTH_PACK, null)).toBe('2026-08')
  })

  it('keeps a chosen period and ignores keys that are not periods', () => {
    expect(resolvePhoneColumnKey(STATEMENT.columns, '2026-08')).toBe('2026-08')
    expect(resolvePhoneColumnKey(STATEMENT.columns, 'compare')).toBe('2026-09')
  })

  it('shows the chosen period and the totals, without comparisons', () => {
    expect([...phoneColumnKeys(STATEMENT.columns, '2026-08')].sort()).toEqual(['2026-08', 'total'])
    expect([...phoneColumnKeys(MONTH_PACK, null)].sort()).toEqual(['2026-08', 'ytd'])
  })

  it('offers only period columns as chips', () => {
    expect(phonePeriodColumns(MONTH_PACK).map((c) => c.key)).toEqual(['2026-08', '2026-07', '2025-08'])
  })

  it('adds the dates to chips whose labels repeat', () => {
    const quarter = (key: string, label: string, sublabel: string, to: string): StatementColumn => ({
      ...column(key, 'period', to),
      label,
      sublabel,
    })
    const ltmByQuarters = [
      quarter('2025-Q3', 'III кв.', 'сен 2025', '2025-09-30'),
      quarter('2025-Q4', 'IV кв.', 'окт–дек 2025', '2025-12-31'),
      quarter('2026-Q3', 'III кв.', 'июл–авг 2026', '2026-08-31'),
      column('total', 'total', '2026-08-31'),
    ]
    expect(phoneChipOptions(ltmByQuarters)).toEqual([
      { value: '2025-Q3', label: 'III кв. сен 2025' },
      { value: '2025-Q4', label: 'IV кв.' },
      { value: '2026-Q3', label: 'III кв. июл–авг 2026' },
    ])
  })
})
